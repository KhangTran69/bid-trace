# BidTrace Backup Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the local restore demo to restore uploaded source files and verify their hashes against the restored PostgreSQL rows.

**Architecture:** Keep the current scratch-database workflow. Export one repeatable-read snapshot for both `pg_dump` and source table counts, restore it to a unique scratch database, then archive only source files referenced by that restored database and verify them in a temporary directory. Keep the live database and upload directory unchanged.

**Tech Stack:** Python 3.12+, psycopg 3, PostgreSQL 16 utilities, pytest, tarfile, hashlib.

**Spec:** `docs/superpowers/specs/2026-11-04-bidtrace-backup-integrity-design.md`

## Global Constraints

- Synthetic data only; never print database passwords or file contents.
- Preserve the existing scratch database name and cleanup protections.
- Never modify the working database or upload directory.
- Archive only safe content-addressed keys referenced by the restored snapshot.
- Reject path traversal and non-regular archive members before writing files.
- Add no runtime dependency.

## Review Focus

- **Missing referenced file:** fail clearly before claiming restore success; remove scratch resources.
- **Corrupt referenced file:** compare SHA-256 and fail without touching live uploads.
- **Unsafe storage key or tar member:** reject it; prove extraction cannot escape the temporary root.
- **Concurrent import during backup:** use one exported DB snapshot for dump and count expectations, and select required files from the restored snapshot.
- **Failure during restore or verification:** drop only the unique scratch database and let temporary-directory cleanup remove the archive and restored files.

---

### Task 1: Archive and verify referenced source files

**Files:**
- Modify: `scripts/backup_restore_demo.py`
- Create: `app/services/source_backup.py`
- Create: `tests/test_backup_restore_demo.py`

**Interfaces:**
- `archive_source_files(source_dir: Path, archive_path: Path, documents: Sequence[tuple[str, str]]) -> int` archives and hash-checks database-referenced files.
- `restore_source_archive(archive_path: Path, target_dir: Path) -> None` safely restores regular files to a new temporary directory.
- `verify_source_files(source_dir: Path, documents: Sequence[tuple[str, str]]) -> int` confirms that each key resolves to a regular file with its recorded SHA-256.
- Keep test cases on real temporary files and tar archives; do not mock filesystem behavior.

- [x] Test valid archive/restore preserves exact bytes and verifies hashes.
- [x] Test a missing source file and a mismatched source hash fail clearly.
- [x] Test a traversal member such as `../outside.pdf` is rejected without creating a file outside the restore directory.
- [x] Run the new focused tests and confirm each failure case fails for the expected reason before implementation.
- [x] Implement only the helpers needed to pass those tests; reject symlinks, directories, unsafe keys, duplicate archive names, and files above the existing upload limit.
- [x] Run the focused tests and Ruff.

### Task 2: Integrate the snapshot into the restore demo

**Files:**
- Modify: `scripts/backup_restore_demo.py`
- Test: `tests/test_backup_restore_demo.py`

**Interfaces:**
- The script reads `UPLOAD_DIR` (default `data/uploads`) and `DATABASE_URL` as it does today.
- Export a PostgreSQL snapshot in a read-only repeatable-read transaction; use it for `pg_dump` and expected table counts.
- After restoring the scratch database, query its source-document rows, archive those live files, restore to a temporary folder, and verify every digest.

- [x] Run the script against a disposable PostgreSQL database with an imported synthetic PDF; confirm table counts and file-hash verification are reported.
- [x] Verify missing-file and corrupt-file failures drop the unique scratch database and leave source database counts unchanged.
- [x] Add an automated failure-path test confirming scratch-database and temporary-directory cleanup.
- [x] Print the restored table counts and number of verified source files; make no success claim if either verification fails.
- [x] Run the full PostgreSQL-backed test suite, Ruff, Alembic drift check, and a complete script run.

### Task 3: Document the demonstrated guarantee

**Files:**
- Modify: `README.md`
- Modify: this plan

- [x] Update the database checks section to explain the database snapshot, referenced-file archive, hash verification, and scratch-only cleanup.
- [x] State that this proves local record/file integrity, not production backup or point-in-time recovery.
- [x] Review the final diff and confirm no backup artifacts or source uploads are tracked.

## Rollback

The feature changes only the demo script, tests, and documentation; it adds no migration or persistent backup format. Reverting the commit returns the existing database-only demo.
