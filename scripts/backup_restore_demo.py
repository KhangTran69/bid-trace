"""Back up the local demo DB and restore it into a uniquely named scratch DB."""

import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

TABLES = ("bids", "source_documents", "bid_line_items", "audit_events")


def _counts(database_url: str) -> dict[str, int]:
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        return {
            table: cursor.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
            ).fetchone()[0]
            for table in TABLES
        }


def _pg_env(url) -> dict[str, str]:
    env = os.environ.copy()
    for key in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGSSLMODE"):
        env.pop(key, None)
    env["PGHOST"] = url.host or "localhost"
    if url.port:
        env["PGPORT"] = str(url.port)
    if url.username:
        env["PGUSER"] = url.username
    if url.password:
        env["PGPASSWORD"] = url.password
    if url.query.get("sslmode"):
        env["PGSSLMODE"] = url.query["sslmode"]
    return env


def main() -> None:
    raw_url = os.environ.get("DATABASE_URL")
    if not raw_url:
        raise SystemExit("Set DATABASE_URL to the local BidTrace PostgreSQL database.")
    source_url = make_url(raw_url)
    if not source_url.database:
        raise SystemExit("DATABASE_URL must name the source database.")
    source = source_url.set(drivername="postgresql").render_as_string(hide_password=False)
    admin = source_url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    scratch_name = f"bidtrace_restore_{uuid4().hex[:12]}"
    expected = _counts(source)
    with TemporaryDirectory(prefix="bidtrace-backup-") as temp_dir:
        archive = Path(temp_dir) / "bidtrace.dump"
        env = _pg_env(source_url)
        env["PGDATABASE"] = source_url.database
        subprocess.run(
            ["pg_dump", "--no-owner", "--format=custom", "--file", str(archive)],
            env=env,
            check=True,
        )
        try:
            with psycopg.connect(admin, autocommit=True) as connection:
                connection.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(scratch_name))
                )
            restore_env = _pg_env(source_url)
            restore_env["PGDATABASE"] = scratch_name
            subprocess.run(
                [
                    "pg_restore",
                    "--no-owner",
                    "--exit-on-error",
                    "--dbname",
                    scratch_name,
                    str(archive),
                ],
                env=restore_env,
                check=True,
            )
            restored = _counts(
                source_url.set(database=scratch_name)
                .set(drivername="postgresql")
                .render_as_string(hide_password=False)
            )
            if restored != expected:
                raise RuntimeError(f"Restored counts differ: expected {expected}, got {restored}")
            print(f"Scratch restore verified: {restored}")
        finally:
            with psycopg.connect(admin, autocommit=True) as connection:
                connection.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(scratch_name))
                )
    print("Scratch database removed; the working BidTrace database was not changed.")


if __name__ == "__main__":
    main()
