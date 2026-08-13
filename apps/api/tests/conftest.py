from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_DB = Path("/tmp/parloq-flow-api-pytest.db")
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{TEST_DB}"
os.environ["APP_SECRET_KEY"] = "pytest-only-secret"
os.environ["BITLY_MOCK"] = "true"
os.environ["IP_PROXY_MOCK"] = "true"
os.environ["WA_GATEWAY_MOCK"] = "true"
os.environ["WA_GATEWAY_WEBHOOK_SECRET"] = "pytest-wa-webhook-secret"
os.environ["PROMOTION_SUCCESS_WEBHOOK_SECRET"] = "pytest-promotion-success-secret"
os.environ["TASK_QUEUE_MOCK"] = "true"
os.environ["AUTO_CREATE_TABLES"] = "true"

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_client(client: TestClient) -> TestClient:
    response = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    )
    assert response.status_code == 200
    yield client
    client.post("/api/auth/logout")
