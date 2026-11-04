# BidTrace Design

**Status:** local implementation complete; Compose startup and exact-width viewport checks remain unverified in this environment.

## Intent

Build a small interview demo that shows how bid documents can become accurate, traceable PostgreSQL records. A reviewer should be able to upload one synthetic subcontractor bid document, inspect extracted line items and their source locations, correct and approve them, and export only approved rows.

The supplied repository was empty. Khang asked for a plan, team input, and execution. Lin reviewed the data model, QA reviewed acceptance behavior, DevOps reviewed local operations, and Alexander reviewed the demo flow. Their recommendations converge on one narrow, human-reviewed ingestion path.

## Approaches

| Approach | Tradeoffs |
|---|---|
| Add bid intake to FlowOps | Reuses its PostgreSQL, migration, idempotency, and audit patterns, but joins a construction workflow to an IT workflow platform and expands that existing project. |
| Build a focused BidTrace app | Gives the interview a direct document-to-database story and keeps the code isolated. It adds a small standalone stack, but its scope stays clear. **Chosen.** |
| Build only a parser script | Fastest way to parse a fixture, but it cannot demonstrate review, audit, approval, or a user-visible export gate. |

## Architecture

Use Python 3.12+, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, Jinja2, pypdf, and openpyxl. Serve a responsive server-rendered review page. Run the app and database locally with Docker Compose; keep uploaded sample files in a content-addressed, gitignored local directory.

Each upload creates one bid, one source-document record, and normalized line items in a single database transaction. A deterministic parser accepts one documented text-based PDF layout, CSV, or XLSX. Every parsed item stores its page or sheet/row locator and source excerpt. Re-uploading the same file hash returns the existing bid.

Review edits preserve extracted values, increment a version, and append an immutable audit event. An item can be approved only after its values pass validation. A bid becomes exportable only when all its items are approved. The CSV export uses one database read and includes stable IDs and source locators.

## Data model

- bids: project name, vendor name, status (needs_review or approved), created time.
- source_documents: bid ID, sanitized filename, content SHA-256, parser name/version, storage key, created time. SHA-256 is unique for idempotency.
- bid_line_items: bid/document IDs, source locator and excerpt, extracted description/quantity/unit/unit price, reviewed values, status (needs_review, corrected, approved), optimistic-lock version.
- audit_events: entity type/ID, actor (demo-reviewer), action, before/after JSONB, timestamp. A PostgreSQL trigger rejects event updates and deletes.

## Goals

- Import synthetic text-PDF and tabular fixtures and show where each line item came from.
- Make retries safe and imports atomic: malformed inputs create no partial records.
- Let a reviewer correct, approve, and audit line items; reject stale edits.
- Export approved data only, with stable columns and source references.
- Demonstrate a PostgreSQL query plan/index on an isolated temporary fixture, and a scratch-database backup/restore.
- Document a fresh-clone run path and the limits of the demo.

## Non-goals

- OCR, floorplan takeoff, general-purpose PDF/XLSX parsing, LLM extraction, cloud deployment, authentication, real bid/customer documents, multi-tenant account management, live ERP connectors, replication, or production backup policy.

## Constraints and safety

- Use synthetic fixtures only. Do not include real bids, personal data, credentials, or customer content.
- Limit uploads to 10 MiB and the .pdf, .csv, and .xlsx formats. Store by content hash; never use the submitted filename as a path.
- Bind the local demo to loopback. The single-reviewer app is not a production service.
- The performance and restore demonstrations must target temporary tables or a separate scratch database. They must not drop or modify the app's working tables.
- No cloud services or external APIs are required.

## Acceptance criteria

1. A fresh clone starts the app and PostgreSQL using the README's documented command; Alembic reaches the current schema.
2. The synthetic PDF, CSV, and XLSX fixtures import into normalized rows with page or sheet/row provenance and visible source excerpts.
3. Uploading the same file twice returns the same bid and creates no additional document or item rows.
4. Unsupported, oversized, corrupt, or malformed files return a clear error and leave no bid, document, line item, or orphaned newly stored file.
5. A reviewer correction retains the original extracted value, writes an audit event with actor/time/before/after, increments the row version, and rejects a stale version with HTTP 409.
6. Approved rows and bid status change transactionally. Export before complete approval is rejected; after approval, the CSV contains exactly the approved rows and includes source locators.
7. The performance demonstration prints actual EXPLAIN (ANALYZE, BUFFERS) plans before and after a relevant index on temporary data, without asserting a fixed speedup.
8. The backup/restore demonstration restores a scratch database and checks the expected synthetic row counts.
9. Automated tests cover parser, import idempotency/rollback, review/audit/concurrency, approval/export, and the main HTML workflow against PostgreSQL. Manual smoke covers keyboard flow and narrow viewport layout.

## Follow-up

After the interview demo, possible extensions are stronger authentication, multi-tenant database row security, broader extraction layouts, and actual ERP integration. None are needed for this version.
