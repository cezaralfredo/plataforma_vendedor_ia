import json
from base64 import b64encode
from time import time

import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

from app.config import Settings, settings
from app.database import get_db
from app.main import create_app
from app.models.admin_account import AdminAccount
from app.models.service import Service
from tests.conftest import TestingSessionLocal


def set_admin_session(client, *, signer=None, **overrides):
    session = {
        "admin_account_id": 1,
        "auth_version": 1,
        "csrf_token": "fixture-csrf-token",
    }
    session.update(overrides)
    signer = signer or TimestampSigner(client.app.state.settings.admin_session_secret)
    signed = signer.sign(
        b64encode(json.dumps(session).encode())
    )
    client.cookies.set("admin_session", signed.decode(), domain="testserver.local", path="/")


def test_anonymous_admin_page_redirects_to_login(anonymous_client):
    response = anonymous_client.get("/admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"
    assert "www-authenticate" not in response.headers


def test_anonymous_admin_api_returns_json_401_even_accepting_html(anonymous_client):
    response = anonymous_client.get("/admin/api/kpis", headers={"Accept": "text/html"})
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/json"
    assert "www-authenticate" not in response.headers


def test_technical_key_still_reads_admin_api(anonymous_client):
    response = anonymous_client.get("/admin/api/kpis", headers={"X-Admin-Key": settings.admin_api_key})
    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/admin", "/admin/api/kpis"])
def test_basic_is_rejected_without_browser_challenge(anonymous_client, path):
    credentials = b64encode(f"admin:{settings.admin_api_key}".encode()).decode()
    response = anonymous_client.get(
        path, headers={"Authorization": f"Basic {credentials}"}, follow_redirects=False
    )
    assert response.status_code in (303, 401)
    assert "www-authenticate" not in response.headers


def test_current_session_reads_admin_api(anonymous_client):
    set_admin_session(anonymous_client)
    response = anonymous_client.get("/admin/api/kpis")
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "admin_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "max-age=28800" in cookie


def test_session_is_revoked_after_database_version_changes(anonymous_client, db_session):
    set_admin_session(anonymous_client)
    assert anonymous_client.get("/admin/api/kpis").status_code == 200
    account = db_session.get(AdminAccount, 1)
    account.auth_version += 1
    db_session.commit()
    response = anonymous_client.get("/admin/api/kpis")
    assert response.status_code == 401
    assert "auth_version" not in response.text


@pytest.mark.parametrize("overrides", [
    {"admin_account_id": 2}, {"admin_account_id": "1"},
    {"auth_version": "1"}, {"auth_version": True},
    {"csrf_token": None}, {"csrf_token": ""},
])
def test_invalid_session_is_rejected(anonymous_client, overrides):
    set_admin_session(anonymous_client, **overrides)
    assert anonymous_client.get("/admin/api/kpis").status_code == 401


@pytest.mark.parametrize("csrf", [None, "wrong-token"])
def test_cookie_mutation_requires_matching_csrf(anonymous_client, db_session, csrf):
    set_admin_session(anonymous_client)
    headers = {} if csrf is None else {"X-CSRF-Token": csrf}
    response = anonymous_client.post("/admin/api/services", json={"name": "Blocked"}, headers=headers)
    assert response.status_code == 403
    assert "fixture-csrf-token" not in response.text
    assert db_session.query(Service).count() == 0


def test_cookie_mutation_with_matching_csrf_creates_service(anonymous_client, db_session):
    set_admin_session(anonymous_client)
    response = anonymous_client.post(
        "/admin/api/services", json={"name": "Allowed", "price_cents": 5000, "duration_minutes": 60},
        headers={"X-CSRF-Token": "fixture-csrf-token"},
    )
    assert response.status_code == 201
    assert db_session.query(Service).one().name == "Allowed"


def test_technical_mutation_needs_no_csrf_even_with_stale_cookie(anonymous_client):
    set_admin_session(anonymous_client, auth_version=0)
    response = anonymous_client.post(
        "/admin/api/services", json={"name": "Technical", "price_cents": 5000, "duration_minutes": 60},
        headers={"X-Admin-Key": settings.admin_api_key},
    )
    assert response.status_code == 201


def test_invalid_technical_key_does_not_fall_back_to_cookie(anonymous_client):
    set_admin_session(anonymous_client)
    response = anonymous_client.get("/admin/api/kpis", headers={"X-Admin-Key": "incorrect"})
    assert response.status_code == 403


def test_session_with_deleted_account_is_rejected(anonymous_client, db_session):
    set_admin_session(anonymous_client)
    db_session.delete(db_session.get(AdminAccount, 1))
    db_session.commit()
    assert anonymous_client.get("/admin/api/kpis").status_code == 401


def test_cookie_signed_with_another_secret_is_rejected(anonymous_client):
    set_admin_session(anonymous_client, signer=TimestampSigner("incorrect-secret"))
    assert anonymous_client.get("/admin/api/kpis").status_code == 401


def test_session_older_than_eight_hours_is_rejected(anonymous_client):
    class ExpiredSigner(TimestampSigner):
        def get_timestamp(self):
            return int(time()) - 8 * 60 * 60 - 60

    set_admin_session(
        anonymous_client,
        signer=ExpiredSigner(anonymous_client.app.state.settings.admin_session_secret),
    )
    assert anonymous_client.get("/admin/api/kpis").status_code == 401


def test_production_cookie_is_secure_and_uses_application_settings(db_session):
    production_settings = Settings(
        debug=False,
        api_key="a" * 32,
        admin_api_key="b" * 32,
        asaas_webhook_token="c" * 32,
        admin_session_secret="d" * 32,
        admin_recovery_key="e" * 32,
        admin_bootstrap_password="production-fixture-only-123",  # noqa: S106
    )
    app = create_app(production_settings, session_factory=TestingSessionLocal)
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app, base_url="https://testserver") as client:
        set_admin_session(client)
        response = client.get("/admin/api/kpis")
        assert response.status_code == 200
        assert "secure" in response.headers["set-cookie"].lower()
        # The secure cookie issued above must not authenticate a plain HTTP request.
        assert client.get("http://testserver/admin/api/kpis").status_code == 401
        client.cookies.clear()
        assert client.get(
            "/admin/api/kpis", headers={"X-Admin-Key": production_settings.admin_api_key}
        ).status_code == 200


@pytest.mark.parametrize("method,path", [
    ("POST", "/admin/appointments/1/action"),
    ("POST", "/admin/payments/1/action"),
    ("PUT", "/admin/api/services/1"),
    ("DELETE", "/admin/api/services/1"),
    ("POST", "/admin/api/services/1/reactivate"),
    ("POST", "/admin/api/professionals"),
    ("PUT", "/admin/api/professionals/1"),
    ("DELETE", "/admin/api/professionals/1"),
    ("POST", "/admin/api/professionals/1/services"),
    ("DELETE", "/admin/api/professionals/1/services/1"),
    ("POST", "/admin/api/professionals/1/availability"),
    ("PUT", "/admin/api/professionals/1/availability/1"),
    ("DELETE", "/admin/api/professionals/1/availability/1"),
    ("POST", "/admin/api/appointments"),
    ("PUT", "/admin/api/appointments/1"),
    ("DELETE", "/admin/api/appointments/1"),
])
def test_all_admin_mutations_reject_cookie_without_csrf(anonymous_client, method, path):
    set_admin_session(anonymous_client)
    assert anonymous_client.request(method, path, json={}).status_code == 403
