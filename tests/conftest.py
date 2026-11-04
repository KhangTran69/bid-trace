import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.config import Settings


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        pytest.exit("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    return url


@pytest.fixture(scope="session")
def engine(database_url: str):
    engine = create_engine(database_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def clean_database(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "TRUNCATE TABLE audit_events, bid_line_items, source_documents, bids "
            "RESTART IDENTITY CASCADE"
        )
    yield


@pytest.fixture
def client(database_url: str, tmp_path):
    from app.main import create_app

    app = create_app(Settings(database_url=database_url, upload_dir=tmp_path / "uploads"))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def fixtures_dir():
    return os.path.join(os.path.dirname(__file__), "..", "fixtures")
