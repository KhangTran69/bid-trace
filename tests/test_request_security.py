import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import Base
from app.main import create_app
from app.models import BidLineItem
from app.security import SECURITY_HEADERS

CSV_CONTENT = b"description,quantity,unit,unit_price\nwidget,1,ea,2.00\n"
SAME_ORIGIN = "http://127.0.0.1:8000"


@pytest.fixture
def client(tmp_path):
    database_path = tmp_path / "security.sqlite"
    app = create_app(
        Settings(
            database_url=f"sqlite:///{database_path}",
            upload_dir=tmp_path / "uploads",
        )
    )
    engine = app.state.session_factory.kw["bind"]
    Base.metadata.create_all(engine)
    with TestClient(app, base_url=SAME_ORIGIN) as test_client:
        yield test_client
    Base.metadata.drop_all(engine)


def import_bid(client: TestClient):
    return client.post(
        "/imports",
        data={"project_name": "Synthetic project", "vendor_name": "Synthetic vendor"},
        files={"file": ("bid.csv", CSV_CONTENT, "text/csv")},
        follow_redirects=False,
    )


def test_cross_site_import_submission_is_rejected(client):
    response = client.post(
        "/imports",
        data={"project_name": "X", "vendor_name": "Y"},
        files={"file": ("bid.csv", CSV_CONTENT, "text/csv")},
        headers={"sec-fetch-site": "cross-site"},
    )

    assert response.status_code == 403


def test_import_submission_with_foreign_origin_is_rejected(client):
    response = client.post(
        "/imports",
        data={"project_name": "X", "vendor_name": "Y"},
        files={"file": ("bid.csv", CSV_CONTENT, "text/csv")},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403


def test_import_submission_from_another_allowed_origin_is_rejected(client):
    response = client.post(
        "/imports",
        data={"project_name": "X", "vendor_name": "Y"},
        files={"file": ("bid.csv", CSV_CONTENT, "text/csv")},
        headers={"Origin": "http://localhost:8000"},
    )

    assert response.status_code == 403


def test_same_origin_import_submission_is_allowed(client):
    response = import_bid(client)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/bids/")


def test_submission_without_browser_headers_remains_usable(client):
    response = client.post(
        "/imports",
        data={"project_name": "X", "vendor_name": "Y"},
        files={"file": ("bid.csv", CSV_CONTENT, "text/csv")},
        follow_redirects=False,
    )

    assert response.status_code == 303


def test_cross_site_review_submission_is_rejected(client):
    imported = import_bid(client)
    bid_id = imported.headers["location"].rsplit("/", maxsplit=1)[-1]
    with client.app.state.session_factory() as session:
        item_id = session.scalar(
            select(BidLineItem.id).where(BidLineItem.bid_id == int(bid_id))
        )

    response = client.post(
        f"/items/{item_id}/review",
        data={
            "expected_version": "0",
            "action": "save",
            "description": "widget",
            "quantity": "1",
            "unit": "ea",
            "unit_price": "2.00",
        },
        headers={"sec-fetch-site": "cross-site"},
    )

    assert response.status_code == 403


def test_custom_allowed_origins_are_honored(tmp_path):
    database_path = tmp_path / "custom-origin.sqlite"
    app = create_app(
        Settings(
            database_url=f"sqlite:///{database_path}",
            upload_dir=tmp_path / "uploads",
            allowed_review_origins=("http://127.0.0.1:5555",),
        )
    )
    engine = app.state.session_factory.kw["bind"]
    Base.metadata.create_all(engine)
    try:
        with TestClient(app, base_url="http://127.0.0.1:5555") as custom_client:
            allowed = custom_client.post(
                "/imports",
                data={"project_name": "X", "vendor_name": "Y"},
                files={"file": ("bid.csv", CSV_CONTENT, "text/csv")},
                headers={"Origin": "http://127.0.0.1:5555"},
                follow_redirects=False,
            )
            assert allowed.status_code == 303
    finally:
        Base.metadata.drop_all(engine)


def test_every_response_carries_security_headers(client):
    response = client.get("/")

    for header, expected in SECURITY_HEADERS.items():
        assert response.headers[header] == expected


def test_security_headers_apply_to_document_downloads_too(client):
    imported = import_bid(client)
    bid_id = imported.headers["location"].rsplit("/", maxsplit=1)[-1]

    response = client.get(f"/bids/{bid_id}")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
