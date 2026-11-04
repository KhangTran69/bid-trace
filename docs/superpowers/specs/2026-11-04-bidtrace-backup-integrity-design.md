# BidTrace Backup Integrity Design

**Status:** Approved for implementation by Khang on 2026-11-04.

## Intent

Make the existing local restore demo prove that a restored BidTrace database still has the source files referenced by its `source_documents` rows. This strengthens the interview story around data integrity and recovery without broadening document parsing.

## Context

The current `scripts/backup_restore_demo.py` dumps and restores PostgreSQL, then compares table counts. Uploaded files are held separately in the configured upload directory, and the README says they are excluded from that demo. Imports store files under a SHA-256-derived key before committing the corresponding database rows. The application does not modify or delete files referenced by committed rows.

## Decision

Extend the existing one-command demo. Export a repeatable-read PostgreSQL snapshot for `pg_dump` and the expected table counts. Restore the database into the existing uniquely named scratch database, read the snapshot's `storage_key` and `sha256` values from that restored database, archive only those referenced files, and restore them to a temporary directory. Verify each key resolves to a regular file and every file's SHA-256 matches its row. Reject unsafe storage keys and unsafe archive members. Always remove the scratch database and temporary files.

No schema change or new dependency is needed. The working database and upload directory remain read-only during the demo. Existing content-addressed source files are assumed immutable; if a referenced source file is missing or damaged, the demo must fail clearly.

## Alternatives

1. Keep the database-only demo and document the gap. This is the smallest change, but it does not verify that restored records retain their source evidence.
2. Stop the app and snapshot its whole upload volume with the database. This depends on manual quiescing and captures unrelated or orphaned files.
3. **Use a database snapshot and archive only the files referenced by that snapshot.** This keeps the current command and scratch-database model, verifies each file against the database, and avoids copying unrelated files. Chosen for the strongest end-to-end proof with the fewest new moving parts.

## Acceptance criteria

- One documented command restores PostgreSQL and the referenced source files into isolated scratch locations.
- Restored table counts equal the counts from the same PostgreSQL snapshot.
- Every restored document key resolves to one regular file whose SHA-256 matches its restored row.
- Missing or corrupt source files, unsafe keys, and unsafe archive members fail with a clear error and do not write outside the temporary restore directory.
- Success and failure both remove only the scratch database and temporary artifacts; the working database and upload directory remain unchanged.
- An automated failure-path test confirms scratch-database and temporary-directory cleanup after file verification fails.
- Tests cover successful archive/restore, missing file, hash mismatch, and path traversal; the full test suite and lint pass.

## Limits

This is a repeatable local demonstration, not a production backup system, point-in-time recovery procedure, or cloud-volume snapshot. The consistency argument depends on committed source files remaining immutable and on the database row being committed only after its source file is stored.
