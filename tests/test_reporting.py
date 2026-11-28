import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import Base
from app.main import create_app
from app.models import BidLineItem

CSV_A = b"description,quantity,unit,unit_price\nwidget,2,ea,3.50\n"
CSV_B = b"description,quantity,unit,unit_price\nbolt,10,box,1.25\n"


@pytest.fixture
def client(tmp_path):
    database_path = tmp_path / "reporting.sqlite"
    app = create_app(
        Settings(
            database_url=f"sqlite:///{database_path}",
            upload_dir=tmp_path / "uploads",
            auth_enabled=False,
        )
    )
    engine = app.state.session_factory.kw["bind"]
    Base.metadata.create_all(engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(engine)


def import_bid(client: TestClient, project_name: str, vendor_name: str, content: bytes):
    return client.post(
        "/imports",
        data={"project_name": project_name, "vendor_name": vendor_name},
        files={"file": ("bid.csv", content, "text/csv")},
        follow_redirects=False,
    )


def approve_all(client: TestClient, bid_id: int):
    with client.app.state.session_factory() as session:
        item_ids = list(
            session.scalars(select(BidLineItem.id).where(BidLineItem.bid_id == bid_id)).all()
        )
    for item_id in item_ids:
        response = client.post(
            f"/items/{item_id}/review",
            data={
                "expected_version": "0",
                "action": "approve",
                "description": "anything",
                "quantity": "1",
                "unit": "ea",
                "unit_price": "1.00",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303


def test_index_filters_by_search_text(client):
    import_bid(client, "Alpha project", "Northwind", CSV_A)
    import_bid(client, "Beta project", "Southwind", CSV_B)

    response = client.get("/", params={"q": "wind"})
    assert response.status_code == 200
    assert "Alpha project" in response.text
    assert "Beta project" in response.text

    response = client.get("/", params={"q": "north"})
    assert "Alpha project" in response.text
    assert "Beta project" not in response.text


def test_index_filters_by_status(client):
    imported = import_bid(client, "Alpha project", "Northwind", CSV_A)
    bid_id = int(imported.headers["location"].rsplit("/", maxsplit=1)[-1])

    response = client.get("/", params={"status": "needs_review"})
    assert "Alpha project" in response.text
    response = client.get("/", params={"status": "approved"})
    assert "No bids match the current filters." in response.text

    approve_all(client, bid_id)
    response = client.get("/", params={"status": "approved"})
    assert "Alpha project" in response.text


def test_index_rejects_unknown_status_values_by_ignoring_them(client):
    import_bid(client, "Alpha project", "Northwind", CSV_A)

    response = client.get("/", params={"status": "nonsense"})

    assert response.status_code == 200
    assert "Alpha project" in response.text


def test_summary_export_lists_every_bid_with_progress(client):
    imported = import_bid(client, "Alpha project", "Northwind", CSV_A)
    bid_id = int(imported.headers["location"].rsplit("/", maxsplit=1)[-1])
    import_bid(client, "Beta project", "Southwind", CSV_B)
    approve_all(client, bid_id)

    response = client.get("/exports/all.csv")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="bids-summary.csv"'
    lines = response.text.strip().split("\r\n")
    assert lines[0] == (
        "bid_id,project_name,vendor_name,status,item_count,approved_items,total_reviewed_amount"
    )
    assert lines[1] == f"{bid_id},Alpha project,Northwind,approved,1,1,1.00"
    assert lines[2] == f"{bid_id + 1},Beta project,Southwind,needs_review,1,0,12.50"


def test_summary_export_guards_formula_leading_names(client):
    import_bid(client, "=cmd|'/calc'", "Northwind", CSV_A)

    response = client.get("/exports/all.csv")

    assert response.status_code == 200
    assert "'=cmd|'/calc'" in response.text


def test_summary_export_requires_sign_in_when_auth_is_enabled(tmp_path):
    database_path = tmp_path / "reporting-auth.sqlite"
    app = create_app(
        Settings(
            database_url=f"sqlite:///{database_path}",
            upload_dir=tmp_path / "uploads",
            auth_enabled=True,
        )
    )
    Base.metadata.create_all(app.state.session_factory.kw["bind"])
    try:
        with TestClient(app) as authed_client:
            response = authed_client.get("/exports/all.csv", follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"] == "/login"
    finally:
        Base.metadata.drop_all(app.state.session_factory.kw["bind"])
