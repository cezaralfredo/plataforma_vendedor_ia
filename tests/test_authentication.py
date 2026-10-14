import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.main as main_module
from app.config import Settings, settings


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": settings.admin_api_key}


def test_api_rejects_missing_bearer(anonymous_client: TestClient):
    response = anonymous_client.get("/api/users")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_api_accepts_configured_bearer(client: TestClient):
    response = client.get("/api/users")

    assert response.status_code == 200


def test_admin_technical_key_works_without_exposing_secret(anonymous_client: TestClient):
    response = anonymous_client.get("/admin", headers=_admin_headers())

    assert response.status_code == 200
    assert settings.admin_api_key not in response.text


@pytest.mark.parametrize(
    "path",
    ["/admin", "/admin/appointments", "/admin/payments", "/admin/professionals"],
)
def test_admin_pages_do_not_render_authentication_headers(
    anonymous_client: TestClient,
    path: str,
):
    response = anonymous_client.get(path, headers=_admin_headers())

    assert response.status_code == 200
    assert settings.admin_api_key not in response.text
    assert "X-Admin-Key" not in response.text


def test_admin_keeps_legacy_header_for_machine_clients(anonymous_client: TestClient):
    response = anonymous_client.get(
        "/admin/api/kpis",
        headers={"X-Admin-Key": settings.admin_api_key},
    )

    assert response.status_code == 200


def test_metrics_requires_bearer(anonymous_client: TestClient):
    response = anonymous_client.get("/metrics")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_production_rejects_development_secrets():
    with pytest.raises(ValidationError):
        Settings(
            debug=False,
            api_key="dev-api-key-change-in-production",
            admin_api_key="dev-admin-key-change-in-production",
            asaas_webhook_token="",
        )


def test_production_disables_interactive_docs():
    assert hasattr(main_module, "create_app"), "A fábrica da aplicação ainda não existe"
    production_settings = Settings(
        debug=False,
        api_key="a" * 32,
        admin_api_key="b" * 32,
        asaas_webhook_token="c" * 32,
        admin_session_secret="d" * 32,
        admin_recovery_key="e" * 32,
    )

    production_app = main_module.create_app(production_settings)
    paths = {route.path for route in production_app.routes}

    assert "/docs" not in paths
    assert "/redoc" not in paths
    assert "/openapi.json" not in paths
