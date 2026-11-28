import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import Base
from app.main import create_app
from app.models import BidLineItem

CSV_CONTENT = b"description,quantity,unit,unit_price\nwidget,2,ea,3.50\nbolt,10,box,1.25\n"


@pytest.fixture
def client(tmp_path):
    database_path = tmp_path / "dashboard.sqlite"
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


def import_bid(client: TestClient):
    return client.post(
        "/imports",
        data={"project_name": "Dashboard project", "vendor_name": "Dashboard vendor"},
        files={"file": ("bid.csv", CSV_CONTENT, "text/csv")},
        follow_redirects=False,
    )


def first_item_id(client: TestClient, bid_id: int) -> int:
    with client.app.state.session_factory() as session:
        return session.scalar(select(BidLineItem.id).where(BidLineItem.bid_id == bid_id))


def approve_item(client: TestClient, item_id: int, *, price: str = "3.50"):
    return client.post(
        f"/items/{item_id}/review",
        data={
            "expected_version": "0",
            "action": "approve",
            "description": "widget",
            "quantity": "2",
            "unit": "ea",
            "unit_price": price,
        },
        follow_redirects=False,
    )


def test_empty_dashboard_renders_zero_state(client):
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "No audit events recorded yet." in response.text


def test_dashboard_reflects_import_and_review_progress(client):
    imported = import_bid(client)
    bid_id = int(imported.headers["location"].rsplit("/", maxsplit=1)[-1])
    approve_item(client, first_item_id(client, bid_id), price="4.00")

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "bid_imported" in response.text
    assert "item_approved" in response.text
    assert "demo-reviewer" in response.text
    # One of two items approved: corrected totals are 2×4.00 + 10×1.25 = 20.50.
    assert "20.50" in response.text
    # Extracted total 2×3.50 + 10×1.25 = 19.50; variance 1.00.
    assert "19.50" in response.text
    assert "1.00" in response.text


def test_dashboard_aggregates_are_sql_side(client):
    imported = import_bid(client)
    bid_id = int(imported.headers["location"].rsplit("/", maxsplit=1)[-1])
    approve_item(client, first_item_id(client, bid_id))

    from app.services.analytics import collect_dashboard_stats

    with client.app.state.session_factory() as session:
        stats = collect_dashboard_stats(session)

    assert stats.bids_by_status == {"needs_review": 1}
    assert stats.items_by_status["approved"] == 1
    assert stats.items_by_status["needs_review"] == 1
    assert stats.audit_counts == {"bid_imported": 1, "item_approved": 1}
    assert stats.total_extracted_amount.as_tuple().exponent == -2


def test_dashboard_requires_sign_in_when_auth_is_enabled(tmp_path):
    database_path = tmp_path / "dashboard-auth.sqlite"
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
            response = authed_client.get("/dashboard", follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"] == "/login"
    finally:
        Base.metadata.drop_all(app.state.session_factory.kw["bind"])
