# Backup/restore reviewer evidence

## Scope and safety

This demo checks a PostgreSQL snapshot restored to a uniquely named scratch database and the source files referenced by that restored snapshot. Use synthetic records only. The script reads the database named by `DATABASE_URL` and files under `UPLOAD_DIR` (default: `data/uploads`); point both at a dedicated, disposable source database and upload directory. Do not use the shared test database, a developer database, or the regular Compose upload volume.

For a local run, the dedicated source database must already have the BidTrace schema and synthetic records imported from the repository fixtures (`fixtures/bid-demo.pdf`, `.csv`, or `.xlsx`). Its dedicated upload directory must contain the corresponding content-addressed source files. From the repository root, run:

```sh
DATABASE_URL='postgresql+psycopg://bidtrace:bidtrace-local-demo@127.0.0.1:55439/bidtrace_restore_source' \
UPLOAD_DIR='/tmp/bidtrace-restore-source-uploads' \
uv run python scripts/backup_restore_demo.py
```

Adjust the connection values to the dedicated local PostgreSQL instance. The database must already exist and be reachable by the supplied URL; this command does not seed it. The run uses `pg_dump` and `pg_restore`, so those PostgreSQL client programs must be available in the environment running the script.

## Expected evidence

| Case | Expected result |
| --- | --- |
| Synthetic source database and files are valid | Exit successfully; print `Scratch restore verified` with the restored counts and number of source files whose SHA-256 matched; then print that the scratch database and temporary files were removed and the working database and uploads were unchanged. |
| A referenced source file is missing or its bytes do not match the stored SHA-256 | Exit unsuccessfully with a verification error; do not print the success message. |
| An unsafe storage key or archive member is encountered | Reject it with a verification error; archive restoration must not write outside its temporary restore directory. |

The script drops its uniquely named scratch database in a `finally` block and uses a temporary directory for its dump, archive, and restored files. On success, the final cleanup message is runtime evidence. On failure, cleanup is covered by `tests/test_backup_restore_demo.py::test_restore_failure_drops_scratch_database_and_temporary_files`; that test simulates restore, count-check, missing-file, and hash-verification failures, and asserts that the scratch database is dropped and the temporary directory removed. It mocks the database and subprocess calls, so it is not evidence of a real PostgreSQL failure run.

## CI status and limits

**Restore-demo CI evidence: pending.** The workflow defines a separate PostgreSQL 16 job with a dedicated `bidtrace_restore_source` database, temporary upload and scratch directories, and success, missing-file, and corrupted-file scenarios. Its synthetic seeder uses a `.csv` key supported by the restore code. No run has been observed, so no CI pass is claimed here.

This is a local synthetic integrity demonstration. It does not prove production recovery, backup retention, point-in-time recovery, or an RPO/RTO guarantee. Its consistency assumption is that committed source files remain immutable and are stored before their database rows are committed.
