# BidTrace

BidTrace is a local interview demo that turns a small bid document into structured, traceable PostgreSQL records. It imports one synthetic bid, links each line item to its source, lets a reviewer correct and approve the values, records each change, and exports only fully approved rows.

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

The browser review form rejects requests marked cross-site by Fetch Metadata and requests whose `Origin` header is present but invalid, different, or outside the documented loopback origins (`http://127.0.0.1:8000` and `http://localhost:8000`). Non-browser clients that omit both headers remain usable. This check limits cross-site browser submissions; it does not add authentication or make the demo suitable for deployment on an untrusted network.

## Database checks

Compose starts PostgreSQL 16, waits for its health check, applies Alembic migrations, then starts the app. To inspect the applied revision:

```sh
docker compose exec app alembic current
```

The plan demo creates 100,000 synthetic rows in a temporary table and prints `EXPLAIN (ANALYZE, BUFFERS)` before and after an index. It drops the table at commit and never touches the app tables:

```sh
docker compose exec app python scripts/explain_query.py
```

The backup/restore demo exports one repeatable-read database snapshot, restores it to a uniquely named scratch database, and compares the four table counts. It then archives only the source files referenced by that restored snapshot, restores them to a temporary directory, and checks that every file exists and matches its recorded SHA-256. Missing or damaged files fail the demo. The scratch database and all temporary files are removed on success or failure; the working database and upload directory are not changed:

```sh
docker compose exec app python scripts/backup_restore_demo.py
```

This demonstrates local database-and-file integrity for BidTrace's content-addressed, immutable source files. It is not a production backup system or point-in-time recovery procedure.

See the [backup/restore reviewer evidence guide](docs/backup-restore-evidence.md) for the isolated synthetic run command, expected outcomes, cleanup evidence, and current CI status.

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

## Change-area map

| Change area | Owning code | Focused evidence |
|-------------|-------------|------------------|
| Parse and import a source document; preserve source locations and avoid partial records | [`app/parsers.py`](app/parsers.py), [`app/services/imports.py`](app/services/imports.py), import route in [`app/main.py`](app/main.py#L103) | [`tests/test_parsers.py`](tests/test_parsers.py), [idempotency](tests/test_workflow.py#L28), and [rollback cleanup](tests/test_workflow.py#L139) |
| Correct or approve a line, retain audit history, reject stale edits, and gate CSV export | [`app/services/reviews.py`](app/services/reviews.py), [`app/services/exports.py`](app/services/exports.py), [review](app/main.py#L174) and [export](app/main.py#L218) routes | Review and audit workflow cases in [`tests/test_workflow.py`](tests/test_workflow.py#L331); approval-only export at [`test_only_fully_approved_bid_can_be_exported`](tests/test_workflow.py#L428) |
| Serve a stored source document only when its content hash matches | Document route in [`app/main.py`](app/main.py#L235) | Exact-byte, mismatch, missing-file, and path-containment cases in [`tests/test_source_document_download.py`](tests/test_source_document_download.py#L48) |
| Change persisted tables, types, or audit immutability | [`app/models.py`](app/models.py), [`app/migrations/versions/`](app/migrations/versions/) | [`tests/test_schema.py`](tests/test_schema.py); CI also runs Alembic's schema-drift check |
| Change the isolated database-and-file restore demonstration | [`scripts/backup_restore_demo.py`](scripts/backup_restore_demo.py), [`app/services/source_backup.py`](app/services/source_backup.py) | [`tests/test_backup_restore_demo.py`](tests/test_backup_restore_demo.py), then follow the [restore evidence guide](docs/backup-restore-evidence.md) for the real local run and current CI status |

The PostgreSQL-backed workflow tests need the disposable test database described above. The restore guide distinguishes mocked failure-cleanup coverage from a real PostgreSQL restore run and marks the hosted restore run pending.

## Demo limits

This repository intentionally demonstrates a narrow and auditable ingestion path. It does not implement OCR, generalized construction takeoff, tenant accounts, authentication, real ERP/CRM integrations, cloud hosting, replication, or production recovery guarantees. PDF extraction supports only the documented text fixture layout.
