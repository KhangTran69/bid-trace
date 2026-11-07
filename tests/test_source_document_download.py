from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import MAX_UPLOAD_BYTES, Settings
from app.db import Base
from app.main import create_app
from app.models import Bid, SourceDocument


@pytest.fixture
def client(tmp_path):
    database_path = tmp_path / "documents.sqlite"
    upload_dir = tmp_path / "uploads"
    app = create_app(Settings(database_url=f"sqlite:///{database_path}", upload_dir=upload_dir))
    engine = app.state.session_factory.kw["bind"]
    Base.metadata.create_all(engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(engine)


def add_document(client, content: bytes, *, filename="source.pdf", digest=None, key=None):
    upload_dir = client.app.state.settings.upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    storage_key = key or "source.pdf"
    if not storage_key.startswith("../"):
        (upload_dir / storage_key).write_bytes(content)
    with Session(client.app.state.session_factory.kw["bind"]) as session:
        bid = Bid(project_name="Synthetic project", vendor_name="Synthetic vendor")
        session.add(bid)
        session.flush()
        document = SourceDocument(
            bid_id=bid.id,
            filename=filename,
            sha256=digest or sha256(content).hexdigest(),
            parser_name="test",
            storage_key=storage_key,
        )
        session.add(document)
        session.commit()
        return document.id


def test_document_download_serves_exact_bytes_when_digest_matches(client):
    content = b"synthetic PDF bytes\x00\xff"
    document_id = add_document(client, content)

    response = client.get(f"/documents/{document_id}")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-disposition"] == 'inline; filename="source.pdf"'


def test_document_download_returns_empty_unavailable_response_on_digest_mismatch(client):
    document_id = add_document(client, b"corrupted bytes", digest="0" * 64)

    response = client.get(f"/documents/{document_id}")

    assert response.status_code == 404
    assert response.content == b""


def test_document_download_returns_empty_unavailable_response_when_file_is_missing(client):
    document_id = add_document(client, b"synthetic PDF bytes")
    (client.app.state.settings.upload_dir / "source.pdf").unlink()

    response = client.get(f"/documents/{document_id}")

    assert response.status_code == 404
    assert response.content == b""


def test_document_download_serves_checked_bytes_if_file_changes_after_read(client, monkeypatch):
    content = b"bytes checked against the stored digest"
    document_id = add_document(client, content)
    source_path = client.app.state.settings.upload_dir / "source.pdf"
    replacement = b"different bytes written after the integrity check"
    original_open = Path.open
    read_count = 0

    class ReadThenChange:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size=-1):
            nonlocal read_count
            content_read = self.stream.read(size)
            read_count += 1
            source_path.write_bytes(replacement)
            return content_read

    def change_file_after_read(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if path == source_path and mode == "rb":
            return ReadThenChange(stream)
        return stream

    monkeypatch.setattr(Path, "open", change_file_after_read)

    response = client.get(f"/documents/{document_id}")

    assert response.status_code == 200
    assert read_count == 1
    assert response.content == content


def test_document_download_rejects_out_of_root_file_without_content(client):
    outside = client.app.state.settings.upload_dir.parent / "outside.pdf"
    outside.write_bytes(b"synthetic outside file")
    document_id = add_document(
        client,
        b"synthetic outside file",
        key="../outside.pdf",
    )

    response = client.get(f"/documents/{document_id}")

    assert response.status_code == 404
    assert response.content == b""


def test_document_download_reads_no_more_than_the_upload_limit_plus_one(client, monkeypatch):
    content = b"x" * (MAX_UPLOAD_BYTES + 1)
    document_id = add_document(client, content)
    source_path = client.app.state.settings.upload_dir / "source.pdf"
    original_open = Path.open
    read_sizes = []

    class ReadRecorder:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size=-1):
            read_sizes.append(size)
            return self.stream.read(size)

    def record_source_open(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if path == source_path and mode == "rb":
            return ReadRecorder(stream)
        return stream

    monkeypatch.setattr(Path, "open", record_source_open)

    response = client.get(f"/documents/{document_id}")

    assert response.status_code == 404
    assert response.content == b""
    assert read_sizes == [MAX_UPLOAD_BYTES + 1]
