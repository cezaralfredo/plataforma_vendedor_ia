import json
import re
from base64 import b64decode

import pytest
from itsdangerous import TimestampSigner

from app.models.admin_account import AdminAccount

USERNAME = "admin-fixture"
PASSWORD = "fixture-password-only-123"  # noqa: S105
RECOVERY_KEY = "fixture-recovery-secret-1234567890"
NEW_PASSWORD = "nova-senha-segura-123"  # noqa: S105


def login(client, **overrides):
    data = {"username": USERNAME, "password": PASSWORD}
    data.update(overrides)
    return client.post("/admin/login", data=data, follow_redirects=False)


def session_data(client):
    signed = client.cookies.get("admin_session")
    assert signed is not None
    payload = TimestampSigner(client.app.state.settings.admin_session_secret).unsign(signed)
    return json.loads(b64decode(payload))


def recover(client, **overrides):
    data = {
        "username": USERNAME,
        "recovery_key": RECOVERY_KEY,
        "new_password": NEW_PASSWORD,
        "confirm_password": NEW_PASSWORD,
    }
    data.update(overrides)
    return client.post("/admin/recover", data=data, follow_redirects=False)


@pytest.mark.parametrize("path,fields", [
    ("/admin/login", {"username": "username", "password": "current-password"}),
    ("/admin/recover", {
        "username": "username", "recovery_key": "off",
        "new_password": "new-password", "confirm_password": "new-password",
    }),
])
def test_public_access_form_has_safe_accessible_fields(anonymous_client, path, fields):
    response = anonymous_client.get(path)
    assert response.status_code == 200
    assert '<html lang="pt-BR">' in response.text
    assert f'action="{path}"' in response.text
    assert 'method="post"' in response.text
    for name, autocomplete in fields.items():
        field = re.search(rf'<input\b[^>]*name="{name}"[^>]*>', response.text)
        assert field is not None
        assert f'autocomplete="{autocomplete}"' in field[0]
        assert f'for="{name}"' in response.text
        if name != "username":
            assert 'type="password"' in field[0]
            assert "value=" not in field[0]
    assert "www-authenticate" not in response.headers


def test_login_creates_fresh_session_and_opens_dashboard(anonymous_client):
    response = login(anonymous_client)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin"
    session = session_data(anonymous_client)
    assert set(session) == {"admin_account_id", "auth_version", "csrf_token"}
    assert session["admin_account_id"] == 1
    assert session["auth_version"] == 1
    assert len(session["csrf_token"]) >= 32
    assert PASSWORD not in json.dumps(session)
    assert anonymous_client.get("/admin").status_code == 200
    assert anonymous_client.get("/admin/api/kpis").status_code == 200
    login(anonymous_client)
    assert session_data(anonymous_client)["csrf_token"] != session["csrf_token"]


def test_invalid_login_is_generic_and_never_reflects_credentials(anonymous_client):
    wrong_password = login(anonymous_client, password="wrong-password-secret")  # noqa: S106
    wrong_user = login(anonymous_client, username="unknown-user-secret")
    missing = anonymous_client.post("/admin/login", data={}, follow_redirects=False)
    assert wrong_password.status_code == wrong_user.status_code == missing.status_code == 400
    assert wrong_password.text == wrong_user.text == missing.text
    assert 'role="alert"' in wrong_password.text
    assert "wrong-password-secret" not in wrong_password.text
    assert "unknown-user-secret" not in wrong_user.text
    assert "admin_session" not in anonymous_client.cookies
    assert anonymous_client.get("/admin/api/kpis").status_code == 401


def test_five_failed_logins_block_even_correct_password(anonymous_client, db_session):
    failures = [login(anonymous_client, password="wrong") for _ in range(5)]  # noqa: S106
    blocked = login(anonymous_client)
    assert all(response.status_code == 400 for response in failures)
    assert blocked.status_code == 400
    assert blocked.text == failures[0].text
    db_session.expire_all()
    account = db_session.get(AdminAccount, 1)
    assert account.failed_login_count == 5
    assert account.locked_until is not None
    assert anonymous_client.get("/admin/api/kpis").status_code == 401


def test_logout_form_clears_session_and_returns_to_login(anonymous_client):
    login(anonymous_client)
    dashboard = anonymous_client.get("/admin")
    form = re.search(r'<form\b[^>]*action="/admin/logout"[^>]*>(.*?)</form>', dashboard.text, re.S)
    assert form is not None
    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', form[1])
    assert token is not None
    response = anonymous_client.post("/admin/logout", data={"csrf_token": token[1]}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"
    assert "admin_session" not in anonymous_client.cookies
    assert anonymous_client.get("/admin/api/kpis").status_code == 401


@pytest.mark.parametrize("token", [None, "wrong", "incorreto-é"])
def test_logout_rejects_missing_or_wrong_csrf_without_logging_out(anonymous_client, token):
    login(anonymous_client)
    response = anonymous_client.post(
        "/admin/logout", data={} if token is None else {"csrf_token": token}, follow_redirects=False,
    )
    assert response.status_code == 403
    assert anonymous_client.get("/admin/api/kpis").status_code == 200


def test_logout_accepts_existing_csrf_header_contract(anonymous_client):
    login(anonymous_client)
    token = session_data(anonymous_client)["csrf_token"]
    response = anonymous_client.post("/admin/logout", headers={"X-CSRF-Token": token}, follow_redirects=False)
    assert response.status_code == 303
    assert anonymous_client.get("/admin/api/kpis").status_code == 401


def test_recovery_changes_password_revokes_other_sessions_and_clears_current(anonymous_client, db_session):
    anonymous_client.app.state.settings.admin_recovery_key = RECOVERY_KEY
    login(anonymous_client)
    old_cookie = anonymous_client.cookies.get("admin_session")
    response = recover(anonymous_client)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"
    assert "admin_session" not in anonymous_client.cookies
    db_session.expire_all()
    assert db_session.get(AdminAccount, 1).auth_version == 2
    anonymous_client.cookies.set("admin_session", old_cookie, domain="testserver.local", path="/")
    assert anonymous_client.get("/admin/api/kpis").status_code == 401
    assert login(anonymous_client).status_code == 400
    assert login(anonymous_client, password=NEW_PASSWORD).status_code == 303
    assert anonymous_client.get("/admin").status_code == 200


def test_recovery_accepts_anonymous_user_and_twelve_character_password(anonymous_client):
    anonymous_client.app.state.settings.admin_recovery_key = RECOVERY_KEY
    response = recover(anonymous_client, new_password="1234567890ab", confirm_password="1234567890ab")  # noqa: S106
    assert response.status_code == 303
    assert login(anonymous_client, password="1234567890ab").status_code == 303  # noqa: S106


@pytest.mark.parametrize("overrides", [
    {"username": "unknown"}, {"recovery_key": "wrong-secret"}, {"recovery_key": "chave-inválida"},
    {"new_password": "short", "confirm_password": "short"}, {"confirm_password": "different"},
])
def test_recovery_errors_are_generic_and_leave_password_unchanged(anonymous_client, db_session, overrides):
    anonymous_client.app.state.settings.admin_recovery_key = RECOVERY_KEY
    reference = recover(anonymous_client, recovery_key="wrong-secret")
    response = recover(anonymous_client, **overrides)
    assert response.status_code == reference.status_code == 400
    assert response.text == reference.text
    assert 'role="alert"' in response.text
    assert RECOVERY_KEY not in response.text
    assert NEW_PASSWORD not in response.text
    db_session.expire_all()
    assert db_session.get(AdminAccount, 1).auth_version == 1
    assert login(anonymous_client).status_code == 303


def test_recovery_requires_configured_key_even_when_submitted_key_is_empty(anonymous_client):
    anonymous_client.app.state.settings.admin_recovery_key = ""
    response = recover(anonymous_client, recovery_key="")
    assert response.status_code == 400
    assert login(anonymous_client).status_code == 303
