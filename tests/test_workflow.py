import csv
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import AuditEvent, Bid, BidLineItem, SourceDocument
from app.services.imports import import_bid
from app.services.reviews import review_line_item

pytestmark = pytest.mark.usefixtures("clean_database")


def upload(client, filename: str, content: bytes):
    return client.post(
        "/imports",
        data={"project_name": "Synthetic Library", "vendor_name": "Demo Concrete"},
        files={"file": (filename, content)},
        follow_redirects=False,
    )


def test_import_displays_source_links_and_is_idempotent(client, fixtures_dir, engine):
    content = (Path(fixtures_dir) / "bid-demo.csv").read_bytes()
    first = upload(client, "bid-demo.csv", content)
    assert first.status_code == 303
    bid_path = first.headers["location"]
    second = upload(client, "renamed-bid.csv", content)
    assert second.status_code == 303
    assert second.headers["location"] == bid_path

    page = client.get(bid_path)
    assert page.status_code == 200
    assert "Demo Concrete" in page.text
    assert "row:2" in page.text
    assert "/documents/" in page.text
    with Session(engine) as session:
        assert len(session.scalars(select(Bid)).all()) == 1
        assert len(session.scalars(select(SourceDocument)).all()) == 1
        assert len(session.scalars(select(BidLineItem)).all()) == 2


def test_concurrent_same_file_import_creates_one_bid_and_one_file(client, fixtures_dir, engine):
    content = (Path(fixtures_dir) / "bid-demo.csv").read_bytes()
    upload_dir = client.app.state.settings.upload_dir
    barrier = Barrier(2)

    def import_once():
        with Session(engine, expire_on_commit=False) as session:
            barrier.wait()
            return import_bid(
                session,
                project_name="Synthetic Library",
                vendor_name="Demo Concrete",
                filename="bid-demo.csv",
                content=content,
                storage_dir=upload_dir,
            ).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: import_once(), range(2)))
    assert results[0] == results[1]
    with Session(engine) as session:
        assert len(session.scalars(select(Bid)).all()) == 1
        assert len(session.scalars(select(SourceDocument)).all()) == 1
        assert len(session.scalars(select(BidLineItem)).all()) == 2
    assert len(list(upload_dir.iterdir())) == 1


def test_database_failure_rolls_back_import_and_removes_new_file(client, fixtures_dir, engine):
    content = (Path(fixtures_dir) / "bid-demo.csv").read_bytes()
    upload_dir = client.app.state.settings.upload_dir
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """CREATE FUNCTION reject_bidtrace_import() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'forced audit failure'; END $$"""
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER reject_bidtrace_import BEFORE INSERT ON audit_events
            FOR EACH ROW WHEN (NEW.action = 'bid_imported')
            EXECUTE FUNCTION reject_bidtrace_import()"""
        )
    try:
        with Session(engine) as session, pytest.raises(SQLAlchemyError):
            import_bid(
                session,
                project_name="Synthetic Library",
                vendor_name="Demo Concrete",
                filename="bid-demo.csv",
                content=content,
                storage_dir=upload_dir,
            )
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "DROP TRIGGER IF EXISTS reject_bidtrace_import ON audit_events"
            )
            connection.exec_driver_sql("DROP FUNCTION IF EXISTS reject_bidtrace_import()")

    with Session(engine) as session:
        assert len(session.scalars(select(Bid)).all()) == 0
        assert len(session.scalars(select(SourceDocument)).all()) == 0
        assert len(session.scalars(select(BidLineItem)).all()) == 0
    assert not upload_dir.exists() or list(upload_dir.iterdir()) == []


def test_pdf_and_xlsx_fixtures_import(client, fixtures_dir, engine):
    for name in ("bid-demo.pdf", "bid-demo.xlsx"):
        response = upload(client, name, (Path(fixtures_dir) / name).read_bytes())
        assert response.status_code == 303
    with Session(engine) as session:
        assert len(session.scalars(select(Bid)).all()) == 2
        assert len(session.scalars(select(BidLineItem)).all()) == 4
        pdf_document = session.scalar(
            select(SourceDocument).where(SourceDocument.filename == "bid-demo.pdf")
        )
        pdf_document_id = pdf_document.id
    assert (
        client.get(f"/documents/{pdf_document_id}")
        .headers["content-disposition"]
        .startswith("inline;")
    )


def test_untrusted_filename_is_sanitized_and_source_file_remains_retrievable(
    client, fixtures_dir, engine
):
    content = (Path(fixtures_dir) / "bid-demo.csv").read_bytes()
    response = upload(client, "../../bid-demo.csv", content)
    assert response.status_code == 303
    with Session(engine) as session:
        document = session.scalar(select(SourceDocument))
        assert document.filename == "bid-demo.csv"
        document_id = document.id
    retrieved = client.get(f"/documents/{document_id}")
    assert retrieved.status_code == 200
    assert retrieved.content == content


def test_review_audit_failure_rolls_back_approval(client, fixtures_dir, engine):
    upload(
        client,
        "bid-demo.csv",
        (Path(fixtures_dir) / "bid-demo.csv").read_bytes(),
    )
    with Session(engine) as session:
        item = session.scalar(select(BidLineItem).order_by(BidLineItem.id))
        item_id = item.id
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """CREATE FUNCTION reject_bidtrace_review() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'forced review audit failure'; END $$"""
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER reject_bidtrace_review BEFORE INSERT ON audit_events
            FOR EACH ROW WHEN (NEW.action = 'item_approved')
            EXECUTE FUNCTION reject_bidtrace_review()"""
        )
    try:
        with Session(engine) as session, pytest.raises(SQLAlchemyError):
            review_line_item(
                session,
                item_id=item_id,
                expected_version=0,
                values={
                    "description": "Concrete pour",
                    "quantity": "12",
                    "unit": "CY",
                    "unit_price": "145.50",
                },
                action="approve",
            )
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "DROP TRIGGER IF EXISTS reject_bidtrace_review ON audit_events"
            )
            connection.exec_driver_sql("DROP FUNCTION IF EXISTS reject_bidtrace_review()")
    with Session(engine) as session:
        item = session.get(BidLineItem, item_id)
        assert item.status == "needs_review"
        assert item.version == 0
        assert (
            len(
                session.scalars(
                    select(AuditEvent).where(AuditEvent.entity_type == "line_item")
                ).all()
            )
            == 0
        )


def test_corrupt_upload_leaves_no_partial_records_or_file(client, engine, tmp_path):
    response = upload(client, "broken.pdf", b"not a PDF")
    assert response.status_code == 400
    assert "could not be read" in response.text.lower() or "valid pdf" in response.text.lower()
    with Session(engine) as session:
        assert len(session.scalars(select(Bid)).all()) == 0
        assert len(session.scalars(select(SourceDocument)).all()) == 0
        assert len(session.scalars(select(BidLineItem)).all()) == 0
    upload_dir = client.app.state.settings.upload_dir
    assert not upload_dir.exists() or list(upload_dir.iterdir()) == []


def test_oversized_upload_preserves_existing_bid_list_and_stores_nothing_new(
    client, fixtures_dir, engine
):
    valid = (Path(fixtures_dir) / "bid-demo.csv").read_bytes()
    assert upload(client, "bid-demo.csv", valid).status_code == 303
    upload_dir = client.app.state.settings.upload_dir
    files_before = sorted(path.name for path in upload_dir.iterdir())

    oversized = upload(
        client,
        "too-large.csv",
        b"x" * (10 * 1024 * 1024 + 1),
    )
    assert oversized.status_code == 400
    assert "Uploads must be 10 MiB or smaller" in oversized.text
    assert "Synthetic Library" in oversized.text
    assert sorted(path.name for path in upload_dir.iterdir()) == files_before
    with Session(engine) as session:
        assert len(session.scalars(select(Bid)).all()) == 1


def test_missing_bid_and_document_are_not_found(client):
    assert client.get("/bids/999999").status_code == 404
    assert client.get("/bids/999999/export.csv").status_code == 404
    assert client.get("/documents/999999").status_code == 404


def test_review_preserves_extraction_audits_changes_and_rejects_stale_edits(
    client, fixtures_dir, engine
):
    upload_response = upload(
        client, "bid-demo.csv", (Path(fixtures_dir) / "bid-demo.csv").read_bytes()
    )
    bid_url = upload_response.headers["location"]
    with Session(engine) as session:
        item = session.scalar(select(BidLineItem).order_by(BidLineItem.id))
        item_id = item.id
        original = item.extracted_description

    saved = client.post(
        f"/items/{item_id}/review",
        data={
            "expected_version": "0",
            "action": "save",
            "description": "Concrete placement",
            "quantity": "13",
            "unit": "CY",
            "unit_price": "145.50",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert "Concrete placement" in client.get(bid_url).text
    stale = client.post(
        f"/items/{item_id}/review",
        data={
            "expected_version": "0",
            "action": "approve",
            "description": "Old edit",
            "quantity": "13",
            "unit": "CY",
            "unit_price": "145.50",
        },
        follow_redirects=False,
    )
    assert stale.status_code == 409
    with Session(engine) as session:
        item = session.get(BidLineItem, item_id)
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.entity_type == "line_item", AuditEvent.entity_id == item_id
            )
        )
        assert item.extracted_description == original
        assert item.reviewed_description == "Concrete placement"
        assert item.version == 1
        assert event.before_values["description"] == original
        assert event.after_values["description"] == "Concrete placement"

    with Session(engine) as session:
        bid_id = session.scalar(select(Bid.id))
    assert client.get(f"/bids/{bid_id}/export.csv").status_code == 409


def test_invalid_review_values_do_not_change_row_or_add_audit(client, fixtures_dir, engine):
    response = upload(
        client,
        "bid-demo.csv",
        (Path(fixtures_dir) / "bid-demo.csv").read_bytes(),
    )
    with Session(engine) as session:
        item = session.scalar(select(BidLineItem).order_by(BidLineItem.id))
        item_id = item.id

    invalid = client.post(
        f"/items/{item_id}/review",
        data={
            "expected_version": "0",
            "action": "save",
            "description": "Concrete placement",
            "quantity": "-1",
            "unit": "CY",
            "unit_price": "145.50",
        },
    )
    assert invalid.status_code == 422
    assert "Quantity must be positive" in invalid.text
    with Session(engine) as session:
        item = session.get(BidLineItem, item_id)
        assert item.reviewed_description == "Concrete pour"
        assert item.version == 0
        assert (
            len(
                session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.entity_type == "line_item", AuditEvent.entity_id == item_id
                    )
                ).all()
            )
            == 0
        )
    assert response.status_code == 303


def test_only_fully_approved_bid_can_be_exported(client, fixtures_dir, engine):
    response = upload(client, "bid-demo.csv", (Path(fixtures_dir) / "bid-demo.csv").read_bytes())
    assert response.status_code == 303
    with Session(engine) as session:
        bid = session.scalar(select(Bid))
        items = session.scalars(select(BidLineItem).order_by(BidLineItem.id)).all()
        bid_id = bid.id
        item_ids = [item.id for item in items]

    export_url = f"/bids/{bid_id}/export.csv"
    assert client.get(export_url).status_code == 409
    for index, item_id in enumerate(item_ids):
        approved = client.post(
            f"/items/{item_id}/review",
            data={
                "expected_version": "0",
                "action": "approve",
                "description": "=FORMULA()" if index == 0 else "Rebar installation",
                "quantity": "12" if index == 0 else "850",
                "unit": "CY" if index == 0 else "LB",
                "unit_price": "145.50" if index == 0 else "2.40",
            },
            follow_redirects=False,
        )
        assert approved.status_code == 303
        if index == 0:
            assert client.get(export_url).status_code == 409

    result = client.get(export_url)
    assert result.status_code == 200
    assert result.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(StringIO(result.text)))
    assert len(rows) == 2
    assert rows[0]["description"] == "'=FORMULA()"
    assert rows[0]["amount"] == "1746.00"
    assert rows[0]["source_locator"] == "row:2"
    assert rows[1]["source_locator"] == "row:3"
    with Session(engine) as session:
        assert session.get(Bid, bid_id).status == "approved"
        assert (
            len(
                session.scalars(
                    select(AuditEvent).where(AuditEvent.action == "item_approved")
                ).all()
            )
            == 2
        )
