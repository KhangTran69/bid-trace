"""Back up the local demo DB and referenced source files into scratch locations."""

import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from app.services.source_backup import (
    SourceDocumentRecord,
    archive_source_files,
    restore_source_archive,
    verify_source_files,
)

TABLES = ("bids", "source_documents", "bid_line_items", "audit_events")


def _counts(connection: psycopg.Connection) -> dict[str, int]:
    return {
        table: connection.execute(
            sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
        ).fetchone()[0]
        for table in TABLES
    }


def _source_documents(database_url: str) -> list[SourceDocumentRecord]:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            "SELECT storage_key, sha256 FROM source_documents ORDER BY id"
        ).fetchall()
    return [(storage_key, digest) for storage_key, digest in rows]


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
    upload_dir = Path(os.environ.get("UPLOAD_DIR", "data/uploads"))
    with TemporaryDirectory(prefix="bidtrace-backup-") as temp_dir:
        temp_root = Path(temp_dir)
        database_archive = temp_root / "bidtrace.dump"
        source_archive = temp_root / "source-files.tar.gz"
        restored_upload_dir = temp_root / "restored-uploads"
        env = _pg_env(source_url)
        env["PGDATABASE"] = source_url.database
        with psycopg.connect(source) as snapshot_connection:
            snapshot_connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            snapshot_id = snapshot_connection.execute("SELECT pg_export_snapshot()").fetchone()[0]
            expected = _counts(snapshot_connection)
            subprocess.run(
                [
                    "pg_dump",
                    "--snapshot",
                    snapshot_id,
                    "--no-owner",
                    "--format=custom",
                    "--file",
                    str(database_archive),
                ],
                env=env,
                check=True,
            )

        scratch_created = False
        try:
            with psycopg.connect(admin, autocommit=True) as connection:
                connection.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(scratch_name))
                )
            scratch_created = True
            restore_env = _pg_env(source_url)
            restore_env["PGDATABASE"] = scratch_name
            subprocess.run(
                [
                    "pg_restore",
                    "--no-owner",
                    "--exit-on-error",
                    "--dbname",
                    scratch_name,
                    str(database_archive),
                ],
                env=restore_env,
                check=True,
            )
            restored_url = (
                source_url.set(database=scratch_name)
                .set(drivername="postgresql")
                .render_as_string(hide_password=False)
            )
            with psycopg.connect(restored_url) as connection:
                restored = _counts(connection)
            if restored != expected:
                raise RuntimeError(f"Restored counts differ: expected {expected}, got {restored}")

            source_documents = _source_documents(restored_url)
            archived_files = archive_source_files(upload_dir, source_archive, source_documents)
            restore_source_archive(source_archive, restored_upload_dir)
            verified_files = verify_source_files(restored_upload_dir, source_documents)
            if archived_files != verified_files:
                raise RuntimeError(
                    f"Source-file counts differ: archived {archived_files}, "
                    f"verified {verified_files}"
                )
            print(
                "Scratch restore verified: "
                f"{restored}; {verified_files} source file(s) matched their SHA-256."
            )
        finally:
            if scratch_created:
                with psycopg.connect(admin, autocommit=True) as connection:
                    connection.execute(
                        sql.SQL("DROP DATABASE {}").format(sql.Identifier(scratch_name))
                    )
    print("Scratch database and files removed; the working database and uploads were not changed.")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(f"Backup/restore verification failed: {error}") from None
