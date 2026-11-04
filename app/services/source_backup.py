"""Safe backup and restore helpers for content-addressed source documents."""

import re
import tarfile
from collections.abc import Sequence
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from app.config import MAX_UPLOAD_BYTES

SourceDocumentRecord = tuple[str, str]
_STORAGE_KEY_PATTERN = re.compile(r"([0-9a-f]{64})\.(pdf|csv|xlsx)\Z")


def _validate_record(storage_key: str, expected_sha256: str) -> None:
    match = _STORAGE_KEY_PATTERN.fullmatch(storage_key)
    if not match or match.group(1) != expected_sha256:
        raise RuntimeError(f"Unsafe source storage key: {storage_key!r}")


def _regular_source_path(source_dir: Path, storage_key: str) -> Path:
    _validate_record(storage_key, storage_key.split(".", maxsplit=1)[0])
    root = source_dir.resolve()
    path = root / storage_key
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Source file is missing or not a regular file: {storage_key}")
    if path.resolve().parent != root:
        raise RuntimeError(f"Unsafe source storage path: {storage_key!r}")
    return path


def archive_source_files(
    source_dir: Path,
    archive_path: Path,
    documents: Sequence[SourceDocumentRecord],
) -> int:
    """Archive exactly the database-referenced source files after checking their hashes."""
    seen: set[str] = set()
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, mode="w:gz") as archive:
        for storage_key, expected_sha256 in documents:
            _validate_record(storage_key, expected_sha256)
            if storage_key in seen:
                raise RuntimeError(f"Duplicate source storage key: {storage_key}")
            seen.add(storage_key)
            path = _regular_source_path(source_dir, storage_key)
            if path.stat().st_size > MAX_UPLOAD_BYTES:
                raise RuntimeError(f"Source file exceeds the upload limit: {storage_key}")
            content = path.read_bytes()
            if len(content) != path.stat().st_size or len(content) > MAX_UPLOAD_BYTES:
                raise RuntimeError(f"Source file exceeds the upload limit: {storage_key}")
            actual_sha256 = sha256(content).hexdigest()
            if actual_sha256 != expected_sha256:
                raise RuntimeError(
                    f"Source file SHA-256 does not match database record: {storage_key}"
                )
            member = tarfile.TarInfo(name=storage_key)
            member.size = len(content)
            member.mode = 0o600
            member.mtime = 0
            archive.addfile(member, BytesIO(content))
    return len(seen)


def restore_source_archive(archive_path: Path, target_dir: Path) -> None:
    """Restore regular content-addressed files without honoring archive paths or links."""
    target_dir.mkdir(parents=True, exist_ok=False)
    seen: set[str] = set()
    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive:
            if not member.isfile():
                raise RuntimeError(
                    f"Unsafe archive member (only regular files are allowed): {member.name!r}"
                )
            match = _STORAGE_KEY_PATTERN.fullmatch(member.name)
            if not match:
                raise RuntimeError(f"Unsafe archive member: {member.name!r}")
            if member.name in seen:
                raise RuntimeError(f"Duplicate archive member: {member.name}")
            if member.size < 0 or member.size > MAX_UPLOAD_BYTES:
                raise RuntimeError(f"Archive member exceeds the upload limit: {member.name}")
            seen.add(member.name)
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError(f"Could not read archive member: {member.name}")
            with source:
                content = source.read(MAX_UPLOAD_BYTES + 1)
            if len(content) != member.size or len(content) > MAX_UPLOAD_BYTES:
                raise RuntimeError(f"Invalid archive member size: {member.name}")
            with (target_dir / member.name).open("xb") as target:
                target.write(content)


def verify_source_files(
    source_dir: Path,
    documents: Sequence[SourceDocumentRecord],
) -> int:
    """Require an exact set of restored files whose bytes match each database hash."""
    expected_keys: set[str] = set()
    root = source_dir.resolve()
    for storage_key, expected_sha256 in documents:
        _validate_record(storage_key, expected_sha256)
        if storage_key in expected_keys:
            raise RuntimeError(f"Duplicate source storage key: {storage_key}")
        expected_keys.add(storage_key)
        path = _regular_source_path(root, storage_key)
        content = path.read_bytes()
        if len(content) > MAX_UPLOAD_BYTES:
            raise RuntimeError(f"Source file exceeds the upload limit: {storage_key}")
        if sha256(content).hexdigest() != expected_sha256:
            raise RuntimeError(
                f"Restored source file SHA-256 does not match database record: {storage_key}"
            )

    actual_keys = {path.name for path in root.iterdir()} if root.exists() else set()
    if actual_keys != expected_keys:
        raise RuntimeError(
            "Restored source files do not match database references: "
            f"missing={sorted(expected_keys - actual_keys)}, "
            f"extra={sorted(actual_keys - expected_keys)}"
        )
    return len(expected_keys)
