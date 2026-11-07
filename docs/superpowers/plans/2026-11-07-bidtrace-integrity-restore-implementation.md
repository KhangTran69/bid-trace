# BidTrace Integrity and Restore Implementation Plan

> **For agentic workers:** Follow the existing repository patterns. Use test-first changes for behavior. Do not merge or deploy.

**Goal:** Make BidTrace source downloads integrity-checked, prove invalid numeric imports leave no partial state, and run its synthetic backup/restore demo in CI with disposable PostgreSQL and isolated files.

**Status (2026-11-07):** Source integrity, numeric-side-effect assertions, CI workflow, synthetic seeder, and reviewer guide are implemented. Focused non-PostgreSQL checks and static review pass. PostgreSQL-backed import checks and hosted restore CI remain pending; the local Docker daemon is unavailable.

**Architecture:** Keep the synchronous FastAPI route and return the exact in-memory bytes whose SHA-256 was checked. Reuse the current parser validation and restore script; add regression proof and a CI invocation with isolated source database and storage. Add a short reviewer guide after the behavior and CI contract are settled.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy, PostgreSQL 16, pytest, GitHub Actions.

**Spec:** `docs/superpowers/plans/2026-11-05-portfolio-roadmap-refresh.md` (BidTrace data integrity and restore gate)

## Global Constraints

- Use synthetic fixtures only; do not use production or personal bid documents.
- Never point the restore demo at a shared or developer database or upload directory.
- Preserve the local-only, unauthenticated demo boundary and existing CSV/XLSX references.
- Do not claim production recovery, retention, or RPO/RTO guarantees.
- Keep the pre-existing `bid-trace` checkout and M4 website branch untouched.
- Work from current `main` commit `c377759ead6257c7ae9574f122c96023943b0927`.

## Review Focus

- A file may change between validation and response: read once, hash those bytes, and serve those same bytes.
- A valid file with the wrong stored digest must return no content; missing and out-of-root files must stay unavailable.
- Invalid quantity or price must not leave a bid, line item, audit event, or staged file.
- CI restore failure must drop the scratch database and remove temporary files, including on missing/corrupt source cases.
- CI must use a dedicated synthetic source database and upload directory, separate from the existing PostgreSQL test database.

---

### Task 1: Verify and serve source bytes

**Owner:** Lin (backend); SWE supports test review.

**Files:** Modify `app/main.py`; add focused tests under `tests/`.

- [x] Add endpoint tests for correct bytes, digest mismatch, missing file, and a file changed after the checked read.
- [x] Run the digest-mismatch regression test against base `c377759`; it failed as expected with HTTP 200 instead of 404.
- [x] Read file bytes once, compare SHA-256 to `SourceDocument.sha256`, and return those same bytes only after a match. Keep unavailable-file responses body-free.
- [x] Run the focused SQLite tests; all six source-download tests pass.

### Task 2: Prove numeric rejection has no side effects

**Owner:** SWE; Lin reviews persistence assumptions.

**Files:** Extend `tests/test_workflow.py` only unless a failing test proves a code change is needed.

- [x] Add import-level boundary cases for excess scale and range.
- [x] Assert zero bids, source documents, line items, audit events, and stored files after each rejected import.
- [ ] Run the targeted PostgreSQL-backed test and confirm it detects any partial state; local PostgreSQL and Docker are unavailable.

### Task 3: Run restore demo in isolated CI

**Owner:** DevOps Bot; Lin reviews database and storage boundaries.

**Files:** Modify `.github/workflows/ci.yml`; add a narrowly scoped synthetic seeding helper only if needed.

- [x] Add a dedicated restore job using PostgreSQL 16, `pg_dump`/`pg_restore`, a separate source database, and a temporary upload directory.
- [ ] Seed synthetic records and verify the successful demo on hosted CI.
- [ ] Verify missing and corrupted source-file failures and cleanup on hosted CI.
- [x] Keep credentials out of logs and artifacts; do not share the existing `bidtrace_test` database or fixture uploads.

### Task 4: Reviewer evidence guide

**Owner:** Alexander; QA bot supplies acceptance wording after implementation.

**Files:** Add a short guide under `docs/` and link it from `README.md` if the repo's existing documentation structure supports it.

- [x] Document commands, synthetic fixture source, expected success/failure outcomes, and cleanup evidence.
- [x] State that the demo proves only the local synthetic workflow, not production recovery.
- [x] Verify guide claims against the workflow definition; hosted CI status remains explicitly pending.

### Task 5: Integrated acceptance and review

**Owners:** QA bot (acceptance), Lebron (code review), Lingxi's Engineer Bot (sequencing); Mikha integrates and verifies.

- [x] Run parser and SQLite source/restore helper tests (33 passed), Ruff, compileall, and `git diff --check` locally.
- [ ] Run the full PostgreSQL suite and real restore workflow on GitHub Actions; record pass/fail and cleanup evidence.
- [x] Review the integrated diff for scope, compatibility, secrets, and fixture isolation; Lebron found no actionable issues.
- [x] Confirm the branch starts at current `main` `c377759`, no unrelated changes are included, and the separate M4 checkout was not touched.

**Done when:** the same source bytes that match the stored SHA-256 are served; invalid numeric imports leave no persisted or staged state; CI passes real restore success and failure cases with cleanup; and reviewer documentation matches the observed evidence. Open a reviewable PR only after the integrated checks and review pass; do not merge or deploy.
