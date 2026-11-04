"""Print PostgreSQL plans against temporary synthetic data only."""

import os

import psycopg
from sqlalchemy.engine import make_url


def main() -> None:
    raw_url = os.environ.get("DATABASE_URL")
    if not raw_url:
        raise SystemExit("Set DATABASE_URL to the local BidTrace PostgreSQL database.")
    url = make_url(raw_url).set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(hide_password=False)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """CREATE TEMP TABLE bidtrace_plan_fixture (
                    line_item_id bigint NOT NULL,
                    bid_id integer NOT NULL
                ) ON COMMIT DROP"""
            )
            cursor.execute(
                "INSERT INTO bidtrace_plan_fixture SELECT n, (n % 1000)::integer "
                "FROM generate_series(1, 100000) AS n"
            )
            cursor.execute("ANALYZE bidtrace_plan_fixture")
            print("Baseline plan (no bid_id index):")
            cursor.execute(
                "EXPLAIN (ANALYZE, BUFFERS) SELECT line_item_id "
                "FROM bidtrace_plan_fixture WHERE bid_id = %s",
                (73,),
            )
            print("\n".join(row[0] for row in cursor.fetchall()))

            cursor.execute("CREATE INDEX bidtrace_plan_bid_idx ON bidtrace_plan_fixture (bid_id)")
            cursor.execute("ANALYZE bidtrace_plan_fixture")
            print("\nIndexed plan (temporary bid_id index):")
            cursor.execute(
                "EXPLAIN (ANALYZE, BUFFERS) SELECT line_item_id "
                "FROM bidtrace_plan_fixture WHERE bid_id = %s",
                (73,),
            )
            print("\n".join(row[0] for row in cursor.fetchall()))
        connection.commit()
    print("\nTemporary table was dropped at commit; no BidTrace tables were changed.")


if __name__ == "__main__":
    main()
