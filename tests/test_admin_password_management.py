import json
import re
from base64 import b64decode

import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

from app.models.admin_account import AdminAccount

PASSWORD = "fixture-password-only-123"  # noqa: S105
NEW_PASSWORD = "nova-senha-segura-123"  # noqa: S105


def login(client, password=PASSWORD):
    return client.post(
        "/admin/login", data={"username": "admin-fixture", "password": password}, follow_redirects=False,
    )


def session_data(client):
    payload = TimestampSigner(client.app.state.settings.admin_session_secret).unsign(client.cookies["admin_session"])
    return json.loads(b64decode(payload))


def change_password(client, **overrides):
    data = {
        "current_password": PASSWORD,
        "new_password": NEW_PASSWORD,
        "confirm_password": NEW_PASSWORD,
        "csrf_token": session_data(client)["csrf_token"],
    }
    data.update(overrides)
    return client.post("/admin/password", data=data, follow_redirects=False)


def test_password_form_requires_session_and_has_accessible_safe_fields(anonymous_client):
    denied = anonymous_client.get("/admin/password", follow_redirects=False)
    assert denied.status_code == 303
    assert denied.headers["location"] == "/admin/login"
    assert anonymous_client.post("/admin/password", data={}).status_code == 401
    login(anonymous_client)
    response = anonymous_client.get("/admin/password")
    assert response.status_code == 200
    assert '<html lang="pt-BR">' in response.text
    form = re.search(r'<form\b[^>]*action="/admin/password"[^>]*>(.*?)</form>', response.text, re.S)
    assert form is not None
    assert 'method="post"' in form[0]
    assert session_data(anonymous_client)["csrf_token"] in form[1]
    for name in ("current_password", "new_password", "confirm_password"):
        field = re.search(rf'<input\b[^>]*name="{name}"[^>]*>', form[1])
        assert field is not None
        assert f'for="{name}"' in form[1]
        assert 'type="password"' in field[0]
        assert "required" in field[0]
        assert "value=" not in field[0]
        autocomplete = "current-password" if name == "current_password" else "new-password"
        assert f'autocomplete="{autocomplete}"' in field[0]
        if name != "current_password":
            assert 'minlength="12"' in field[0]
    dashboard = anonymous_client.get("/admin")
    assert 'href="/admin/password"' in dashboard.text
    assert "Alterar senha" in dashboard.text
    assert 'action="/admin/logout"' in dashboard.text


@pytest.mark.parametrize("overrides", [
    {"current_password": ""}, {"current_password": "incorreta-secreta"},
    {"new_password": "12345678901", "confirm_password": "12345678901"},
    {"new_password": "", "confirm_password": ""},
    {"confirm_password": ""}, {"confirm_password": "diferente-secreta"},
])
def test_invalid_password_form_leaves_password_and_session_unchanged(anonymous_client, db_session, overrides):
    login(anonymous_client)
    old_session = session_data(anonymous_client)
    response = change_password(anonymous_client, **overrides)
    assert response.status_code == 400
    assert 'role="alert"' in response.text
    assert "senha" in response.text
    for secret in (PASSWORD, NEW_PASSWORD, "incorreta-secreta", "diferente-secreta"):
        assert secret not in response.text
    assert session_data(anonymous_client) == old_session
    db_session.expire_all()
    assert db_session.get(AdminAccount, 1).auth_version == 1
    assert login(anonymous_client).status_code == 303


@pytest.mark.parametrize("token", [None, "errado", "inválido-é"])
def test_password_change_requires_valid_csrf(anonymous_client, db_session, token):
    login(anonymous_client)
    response = change_password(anonymous_client, csrf_token=token)
    assert response.status_code == 403
    assert 'role="alert"' in response.text
    assert "atualize" in response.text.lower()
    db_session.expire_all()
    assert db_session.get(AdminAccount, 1).auth_version == 1
    assert login(anonymous_client).status_code == 303


def test_password_change_renews_session_and_revokes_all_old_cookies(anonymous_client, db_session, caplog):
    login(anonymous_client)
    old_cookie = anonymous_client.cookies["admin_session"]
    old_session = session_data(anonymous_client)
    other = TestClient(anonymous_client.app)
    try:
        assert login(other).status_code == 303
        other_cookie = other.cookies["admin_session"]
        other_token = session_data(other)["csrf_token"]
        assert other.get("/admin/api/kpis").status_code == 200
        response = change_password(anonymous_client)
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/password?changed=1"
        new_session = session_data(anonymous_client)
        assert set(new_session) == {"admin_account_id", "auth_version", "csrf_token"}
        assert new_session["admin_account_id"] == 1
        assert new_session["auth_version"] == old_session["auth_version"] + 1
        assert new_session["csrf_token"] != old_session["csrf_token"]
        db_session.expire_all()
        assert db_session.get(AdminAccount, 1).auth_version == 2
        page = anonymous_client.get(response.headers["location"])
        assert page.status_code == 200
        assert 'role="status"' in page.text
        assert "Senha alterada com sucesso" in page.text
        assert new_session["csrf_token"] in page.text
        for secret in (PASSWORD, NEW_PASSWORD):
            assert secret not in page.text + str(response.headers) + json.dumps(new_session) + caplog.text
        assert anonymous_client.get("/admin/api/kpis").status_code == 200
        assert anonymous_client.post(
            "/admin/logout", data={"csrf_token": old_session["csrf_token"]}, follow_redirects=False,
        ).status_code == 403
        for cookie, token in ((old_cookie, old_session["csrf_token"]), (other_cookie, other_token)):
            for method, path in (("GET", "/admin"), ("GET", "/admin/api/kpis"), ("POST", "/admin/password")):
                other.cookies.clear()
                other.cookies.set("admin_session", cookie, domain="testserver.local", path="/")
                revoked = other.request(method, path, headers={"X-CSRF-Token": token}, follow_redirects=False)
                assert revoked.status_code == (303 if path == "/admin" else 401)
        assert login(other).status_code == 400
        assert login(other, NEW_PASSWORD).status_code == 303
        assert anonymous_client.post(
            "/admin/logout", data={"csrf_token": new_session["csrf_token"]}, follow_redirects=False,
        ).status_code == 303
        assert anonymous_client.get("/admin/api/kpis").status_code == 401
    finally:
        other.close()


def test_password_change_accepts_exactly_twelve_characters(anonymous_client):
    login(anonymous_client)
    response = change_password(anonymous_client, new_password="1234567890ab", confirm_password="1234567890ab")  # noqa: S106
    assert response.status_code == 303
    assert login(anonymous_client, "1234567890ab").status_code == 303


@pytest.mark.parametrize("valid", [False, True])
def test_csrf_header_takes_precedence_over_form(anonymous_client, valid):
    login(anonymous_client)
    token = session_data(anonymous_client)["csrf_token"]
    response = anonymous_client.post(
        "/admin/password",
        data={
            "current_password": PASSWORD, "new_password": NEW_PASSWORD,
            "confirm_password": NEW_PASSWORD, "csrf_token": "wrong" if valid else token,
        },
        headers={"X-CSRF-Token": token if valid else "wrong"}, follow_redirects=False,
    )
    assert response.status_code == (303 if valid else 403)


def test_technical_key_does_not_create_password_management_session(anonymous_client):
    headers = {"X-Admin-Key": anonymous_client.app.state.settings.admin_api_key}
    for method in ("GET", "POST"):
        response = anonymous_client.request(method, "/admin/password", headers=headers, follow_redirects=False)
        assert response.status_code == 403
        assert "sessão" in response.text
    assert "admin_session" not in anonymous_client.cookies
