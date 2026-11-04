import tarfile
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.services.source_backup import (
    archive_source_files,
    restore_source_archive,
    verify_source_files,
)

_SCRIPT_SPEC = spec_from_file_location(
    "backup_restore_demo", Path(__file__).parents[1] / "scripts" / "backup_restore_demo.py"
)
assert _SCRIPT_SPEC and _SCRIPT_SPEC.loader
backup_restore_demo = module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(backup_restore_demo)


def test_source_archive_round_trip_preserves_and_verifies_file(tmp_path):
    source_dir = tmp_path / "live-uploads"
    source_dir.mkdir()
    content = b"synthetic source document"
    digest = sha256(content).hexdigest()
    storage_key = f"{digest}.pdf"
    (source_dir / storage_key).write_bytes(content)
    archive_path = tmp_path / "source-files.tar.gz"
    restored_dir = tmp_path / "restored-uploads"
    records = [(storage_key, digest)]

    archived_count = archive_source_files(source_dir, archive_path, records)
    restore_source_archive(archive_path, restored_dir)
    verified_count = verify_source_files(restored_dir, records)

    assert archived_count == 1
    assert verified_count == 1
    assert (restored_dir / storage_key).read_bytes() == content
    assert set(source_dir.iterdir()) == {source_dir / storage_key}


def test_source_archive_rejects_missing_referenced_file(tmp_path):
    digest = "a" * 64
    record = (f"{digest}.pdf", digest)

    with pytest.raises(RuntimeError, match="missing or not a regular file"):
        archive_source_files(tmp_path / "live-uploads", tmp_path / "backup.tar.gz", [record])


def test_source_archive_rejects_mismatched_hash(tmp_path):
    source_dir = tmp_path / "live-uploads"
    source_dir.mkdir()
    expected_digest = "a" * 64
    storage_key = f"{expected_digest}.pdf"
    (source_dir / storage_key).write_bytes(b"different content")

    with pytest.raises(RuntimeError, match="SHA-256 does not match"):
        archive_source_files(
            source_dir,
            tmp_path / "backup.tar.gz",
            [(storage_key, expected_digest)],
        )


def test_source_archive_rejects_unsafe_storage_key(tmp_path):
    with pytest.raises(RuntimeError, match="Unsafe source storage key"):
        archive_source_files(
            tmp_path,
            tmp_path / "backup.tar.gz",
            [("../outside.pdf", "a" * 64)],
        )


def test_source_archive_rejects_symlinked_source_file(tmp_path):
    source_dir = tmp_path / "live-uploads"
    source_dir.mkdir()
    content = b"synthetic source document"
    digest = sha256(content).hexdigest()
    storage_key = f"{digest}.pdf"
    outside_file = tmp_path / "outside.pdf"
    outside_file.write_bytes(content)
    (source_dir / storage_key).symlink_to(outside_file)

    with pytest.raises(RuntimeError, match="missing or not a regular file"):
        archive_source_files(
            source_dir,
            tmp_path / "backup.tar.gz",
            [(storage_key, digest)],
        )


def test_restore_rejects_tar_path_traversal(tmp_path):
    archive_path = tmp_path / "hostile.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        payload = b"outside"
        member = tarfile.TarInfo("../outside.pdf")
        member.size = len(payload)
        archive.addfile(member, BytesIO(payload))

    restore_dir = tmp_path / "restored-uploads"
    with pytest.raises(RuntimeError, match="Unsafe archive member"):
        restore_source_archive(archive_path, restore_dir)

    assert not (tmp_path / "outside.pdf").exists()


def test_restore_rejects_tar_symlink(tmp_path):
    archive_path = tmp_path / "symlink.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        member = tarfile.TarInfo(f"{'c' * 64}.pdf")
        member.type = tarfile.SYMTYPE
        member.linkname = "../../outside.pdf"
        archive.addfile(member)

    with pytest.raises(RuntimeError, match="only regular files are allowed"):
        restore_source_archive(archive_path, tmp_path / "restored-uploads")


def test_source_verification_rejects_missing_restored_file(tmp_path):
    digest = "b" * 64

    with pytest.raises(RuntimeError, match="missing or not a regular file"):
        verify_source_files(tmp_path / "restored-uploads", [(f"{digest}.csv", digest)])


def test_source_verification_rejects_corrupt_restored_file(tmp_path):
    restored_dir = tmp_path / "restored-uploads"
    restored_dir.mkdir()
    expected_content = b"expected content"
    digest = sha256(expected_content).hexdigest()
    storage_key = f"{digest}.pdf"
    (restored_dir / storage_key).write_bytes(b"corrupted content")

    with pytest.raises(RuntimeError, match="Restored source file SHA-256 does not match"):
        verify_source_files(restored_dir, [(storage_key, digest)])


@pytest.mark.parametrize(
    ("failure_stage", "expected_error"),
    [
        ("pg_restore", "simulated pg_restore failure"),
        ("table_counts", "Restored counts differ"),
        ("source_archive", "Source file is missing or not a regular file"),
        ("hash_verification", "Restored source file SHA-256 does not match"),
    ],
)
def test_restore_failure_drops_scratch_database_and_temporary_files(
    monkeypatch, tmp_path, failure_stage, expected_error
):
    content = b"synthetic source document"
    digest = sha256(content).hexdigest()
    storage_key = f"{digest}.pdf"
    source_records = [(storage_key, digest)]

    class Result:
        def __init__(self, row=None, rows=None):
            self.row = row
            self.rows = rows or []

        def fetchone(self):
            return self.row

        def fetchall(self):
            return self.rows

    class Connection:
        def __init__(self, database):
            self.database = database

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, *_args):
            query_text = query if isinstance(query, str) else ""
            if self.database == "postgres":
                admin_queries.append(query)
                return Result()
            if query_text == "SELECT pg_export_snapshot()":
                return Result(("snapshot-id",))
            if query_text == "SELECT storage_key, sha256 FROM source_documents ORDER BY id":
                has_file_record = failure_stage in {"source_archive", "hash_verification"}
                records = source_records if has_file_record else []
                return Result(rows=records)
            if (
                not query_text
                and self.database.startswith("bidtrace_restore_")
                and failure_stage == "table_counts"
            ):
                return Result((4,))
            return Result((3,))

    admin_queries = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://demo:demo@localhost/bidtrace")
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    if failure_stage == "hash_verification":
        upload_dir.mkdir()
        (upload_dir / storage_key).write_bytes(content)
    monkeypatch.setattr(
        backup_restore_demo.psycopg,
        "connect",
        lambda conninfo, **_kwargs: Connection(make_url(conninfo).database),
    )

    def run(command, **_kwargs):
        if failure_stage == "pg_restore" and command[0] == "pg_restore":
            raise RuntimeError("simulated pg_restore failure")

    monkeypatch.setattr(backup_restore_demo.subprocess, "run", run)
    if failure_stage == "hash_verification":
        real_restore_source_archive = backup_restore_demo.restore_source_archive

        def restore_corrupted_archive(archive_path, target_dir):
            real_restore_source_archive(archive_path, target_dir)
            (target_dir / storage_key).write_bytes(b"corrupted source document")

        monkeypatch.setattr(
            backup_restore_demo, "restore_source_archive", restore_corrupted_archive
        )
    created_tempdirs = []
    real_temporary_directory = backup_restore_demo.TemporaryDirectory

    def temporary_directory(*args, **kwargs):
        directory = real_temporary_directory(*args, **kwargs)
        created_tempdirs.append(Path(directory.name))
        return directory

    monkeypatch.setattr(backup_restore_demo, "TemporaryDirectory", temporary_directory)

    with pytest.raises(RuntimeError) as raised:
        backup_restore_demo.main()

    assert len(admin_queries) == 2
    create_statement = admin_queries[0].as_string(None)
    drop_statement = admin_queries[1].as_string(None)
    scratch_name = create_statement.removeprefix('CREATE DATABASE "').removesuffix('"')
    assert scratch_name.startswith("bidtrace_restore_")
    assert drop_statement == f'DROP DATABASE "{scratch_name}"'
    assert expected_error in str(raised.value)
    assert len(created_tempdirs) == 1
    assert not created_tempdirs[0].exists()
