from app.core.config import settings
from tests.conftest import register


def test_register_returns_token_and_user(client):
    response = client.post(
        "/api/auth/register", json={"email": "New@Example.com", "password": "supersecret123", "full_name": "New"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "new@example.com"
    assert "password" not in str(body).lower()


def test_register_duplicate_email_is_409(client):
    register(client, email="dup@example.com")
    response = client.post("/api/auth/register", json={"email": "DUP@example.com", "password": "supersecret123"})
    assert response.status_code == 409


def test_register_rejects_short_password(client):
    response = client.post("/api/auth/register", json={"email": "a@example.com", "password": "short"})
    assert response.status_code == 422
    assert "password" in response.json()["detail"]


def test_register_rejects_invalid_email(client):
    response = client.post("/api/auth/register", json={"email": "not-an-email", "password": "supersecret123"})
    assert response.status_code == 422


def test_register_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_REGISTRATION", False)
    response = client.post("/api/auth/register", json={"email": "x@example.com", "password": "supersecret123"})
    assert response.status_code == 403


def test_password_is_hashed_not_plaintext(client):
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import User

    register(client, email="hash@example.com", password="supersecret123")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "hash@example.com"))
        assert user.hashed_password != "supersecret123"
        assert user.hashed_password.startswith("$2")


def test_login_success(client):
    register(client, email="login@example.com", password="supersecret123")
    response = client.post("/api/auth/login", json={"email": "login@example.com", "password": "supersecret123"})
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_wrong_password(client):
    register(client, email="login@example.com", password="supersecret123")
    response = client.post("/api/auth/login", json={"email": "login@example.com", "password": "wrong-password"})
    assert response.status_code == 401


def test_login_unknown_email(client):
    response = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever123"})
    assert response.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_rejects_invalid_token(client):
    response = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_me_returns_current_user(client, auth_headers):
    response = client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"


def test_login_rate_limited(client, monkeypatch):
    from app.api.auth import login_limiter

    monkeypatch.setattr(login_limiter, "max_requests", 3)
    for _ in range(3):
        client.post("/api/auth/login", json={"email": "a@example.com", "password": "whatever123"})
    response = client.post("/api/auth/login", json={"email": "a@example.com", "password": "whatever123"})
    assert response.status_code == 429
