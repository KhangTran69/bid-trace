import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.config import Settings
from app.db import Base
from app.main import create_app
from app.models import AuditEvent, User

CSV_CONTENT = b"description,quantity,unit,unit_price\nwidget,1,ea,2.00\n"


@pytest.fixture
def app(tmp_path):
    database_path = tmp_path / "auth.sqlite"
    created = create_app(
        Settings(
            database_url=f"sqlite:///{database_path}",
            upload_dir=tmp_path / "uploads",
            session_secret="auth-test-secret",
        )
    )
    engine = created.state.session_factory.kw["bind"]
    Base.metadata.create_all(engine)
    yield created
    Base.metadata.drop_all(engine)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def make_user(app, username="reviewer", password="correct-horse-battery"):
    with app.state.session_factory() as session, session.begin():
        session.add(
            User(
                username=username,
                password_hash=hash_password(password),
                display_name="Demo Reviewer",
            )
        )
    return username, password


def login(client: TestClient, username: str, password: str):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def test_login_page_is_reachable(client):
    response = client.get("/login")

    assert response.status_code == 200
    assert 'action="/login"' in response.text


def test_anonymous_requests_are_redirected_to_login(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_unknown_username_is_rejected(client):
    make_user(client.app)

    response = login(client, "ghost", "correct-horse-battery")

    assert response.status_code == 401


def test_wrong_password_is_rejected(client):
    username, _ = make_user(client.app)

    response = login(client, username, "not-the-password")

    assert response.status_code == 401
    assert "Invalid username or password." in response.text


def test_successful_login_grants_access(client):
    username, password = make_user(client.app)

    response = login(client, username, password)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert client.get("/").status_code == 200


def test_import_records_the_signed_in_user_as_actor(client):
    username, password = make_user(client.app)
    login(client, username, password)

    response = client.post(
        "/imports",
        data={"project_name": "Synthetic project", "vendor_name": "Synthetic vendor"},
        files={"file": ("bid.csv", CSV_CONTENT, "text/csv")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with client.app.state.session_factory() as session:
        actor = session.scalar(
            select(AuditEvent.actor).where(AuditEvent.action == "bid_imported")
        )
    assert actor == username


def test_logout_clears_the_session(client):
    username, password = make_user(client.app)
    login(client, username, password)

    response = client.post("/logout", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    after = client.get("/", follow_redirects=False)
    assert after.headers["location"] == "/login"


def test_disabled_auth_keeps_anonymous_demo_access(tmp_path):
    database_path = tmp_path / "noauth.sqlite"
    app = create_app(
        Settings(
            database_url=f"sqlite:///{database_path}",
            upload_dir=tmp_path / "uploads",
            auth_enabled=False,
        )
    )
    Base.metadata.create_all(app.state.session_factory.kw["bind"])
    try:
        with TestClient(app) as anonymous_client:
            assert anonymous_client.get("/").status_code == 200
            assert anonymous_client.get("/login", follow_redirects=False).status_code == 404
    finally:
        Base.metadata.drop_all(app.state.session_factory.kw["bind"])
