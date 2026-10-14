from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def test_readiness_checks_database(anonymous_client: TestClient):
    response = anonymous_client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_returns_503_on_database_failure(
    anonymous_client: TestClient,
    monkeypatch,
):
    monkeypatch.setattr(
        Session,
        "execute",
        Mock(side_effect=SQLAlchemyError("offline")),
    )
    response = anonymous_client.get("/ready")
    assert response.status_code == 503
    assert response.json()["detail"] == "Database unavailable"
