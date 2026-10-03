"""Test setup.

By default tests use an in-memory SQLite database, so they run anywhere.
To run them against PostgreSQL instead:

    TEST_DATABASE_URL=postgresql://user@localhost:5432/expense_tracker_test pytest
"""

import os

# Must be set BEFORE the app is imported (settings are read at import time).
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
os.environ["JWT_SECRET"] = "test-secret-that-is-definitely-longer-than-32-characters"
os.environ["ENVIRONMENT"] = "test"
os.environ["ALLOW_REGISTRATION"] = "true"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
os.environ["OPENAI_API_KEY"] = ""  # tests never call the real LLM; they mock it

import pytest
from fastapi.testclient import TestClient

from app.api.auth import login_limiter
from app.api.imports import import_limiter, reprocess_limiter
from app.db.base import Base
from app.db.session import engine
from app.main import app  # also imports every model

SAMPLE_OCR = """Paid to
BLINK COMMERCE PRIVA...

Amount:
¥183

Date:
3 October 2026
1:11 PM

PhonePe Transaction ID:
T2610031311415776289288

Debited from:
XXXXXX096929

UTR:
706226593892

Message:
UPIIntent
"""


@pytest.fixture(scope="session", autouse=True)
def create_schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def clean_tables():
    yield
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())
    login_limiter.reset()
    import_limiter.reset()
    reprocess_limiter.reset()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def register(client, email="me@example.com", password="supersecret123"):
    response = client.post("/api/auth/register", json={"email": email, "password": password, "full_name": "Me"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def auth_headers(client):
    return register(client)


@pytest.fixture
def sample_ocr():
    return SAMPLE_OCR
