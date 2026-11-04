# BidTrace

BidTrace is a small bid document into structured, traceable PostgreSQL records. It imports one synthetic bid, links each line item to its source, lets a reviewer correct and approve the values, records each change, and exports only fully approved rows.

## Run the demo

Requirements: Docker Desktop with Compose, and a browser.

```sh
cp .env.example .env
docker compose up --build
```

Open <http://127.0.0.1:8000>. Try `fixtures/bid-demo.pdf`, `fixtures/bid-demo.csv`, or `fixtures/bid-demo.xlsx`. Enter a project and vendor, inspect the source excerpt for each item, save any correction, and approve each row. The CSV export becomes available after every row is approved.

To stop the app and keep its local demo data:

```sh
docker compose down
```

To remove the Compose database and uploaded files, use `docker compose down -v`. This permanently deletes the local demo data.

## Supported input layouts

- **PDF:** text-based documents with one item per line in the form `ITEM|description|quantity|unit|unit_price`. OCR and arbitrary bid layouts are outside this demo.
- **CSV/XLSX:** first row has exactly `description,quantity,unit,unit_price`; data starts on row 2. XLSX reads the first worksheet.
- **Limits:** PDF, CSV, and XLSX up to 10 MiB. Use synthetic data only; do not upload real bids, customer records, personal data, or credentials.

Each source reference shows the PDF page, CSV row, or XLSX sheet and cell range plus the exact extracted row text. Extraction is a draft: a human must review each line.

## Data model and integrity

- `bids` records project, vendor, and review status.
- `source_documents` stores the sanitized filename, parser version, SHA-256, and content-addressed local storage key. A unique SHA-256 makes retries idempotent.
- `bid_line_items` keeps original extracted values beside reviewed values, with exact source location, status, and optimistic-lock version.
- `audit_events` records the reviewer, timestamp, action, and before/after JSONB values. Review updates and their audit rows commit together. A PostgreSQL trigger rejects audit-row updates and deletes.

Import writes the source file and creates the bid, source document, items, and import audit record transactionally. A failed DB write removes a newly staged source file. Re-uploading identical bytes returns the existing bid. Review forms submit a row version; stale forms receive a conflict rather than overwriting a newer edit. The final item approval and bid status update commit together. CSV export checks approval in PostgreSQL and prefixes formula-leading text to prevent spreadsheet formula execution.

The app has one local demo reviewer and no authentication. Compose binds the app and PostgreSQL ports to loopback. This is not a production security boundary or a backup policy.

## Database checks

Compose starts PostgreSQL 16, waits for its health check, applies Alembic migrations, then starts the app. To inspect the applied revision:

```sh
docker compose exec app alembic current
```

The plan demo creates 100,000 synthetic rows in a temporary table and prints `EXPLAIN (ANALYZE, BUFFERS)` before and after an index. It drops the table at commit and never touches the app tables:

```sh
docker compose exec app python scripts/explain_query.py
```

The backup/restore demo runs `pg_dump`, restores to a uniquely named scratch database, compares the four table counts, and drops only that scratch database:

```sh
docker compose exec app python scripts/backup_restore_demo.py
```

This evidence covers PostgreSQL records only; uploaded source files live in a separate Compose volume and are not included in this `pg_dump` demo.

## Tests and local checks

The tests target a disposable PostgreSQL database named `bidtrace_test`; they truncate only its application tables. Start Compose first, then run:

```sh
uv sync --extra dev
DATABASE_URL='postgresql+psycopg://bidtrace:bidtrace-local-demo@127.0.0.1:55439/bidtrace_test' uv run alembic upgrade head
TEST_DATABASE_URL='postgresql+psycopg://bidtrace:bidtrace-local-demo@127.0.0.1:55439/bidtrace_test' uv run pytest
DATABASE_URL='postgresql+psycopg://bidtrace:bidtrace-local-demo@127.0.0.1:55439/bidtrace_test' uv run alembic check
uv run ruff check .
```

CI runs the migration, schema-drift check, Ruff, and the same PostgreSQL-backed tests on Python 3.12.

## Demo limits

This repository intentionally demonstrates a narrow and auditable ingestion path. It does not implement OCR, generalized construction takeoff, tenant accounts, authentication, real ERP/CRM integrations, cloud hosting, replication, or production recovery guarantees. PDF extraction supports only the documented text fixture layout.
