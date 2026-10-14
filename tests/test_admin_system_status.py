from unittest.mock import Mock

from sqlalchemy.exc import OperationalError

from app.admin.service import AdminService
from app.config import settings


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": settings.admin_api_key}


def test_admin_system_status_reports_only_measured_capabilities(anonymous_client):
    response = anonymous_client.get("/admin/api/system-status", headers=_admin_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["api"] == {"status": "online"}
    assert payload["database"] == {"status": "connected"}
    expected_mode = "sandbox" if "sandbox" in settings.asaas_base_url.lower() else "production"
    assert payload["asaas"] == {"configured": bool(settings.asaas_api_key), "mode": expected_mode}
    assert payload["mcp"] == {"endpoint_enabled": True}
    assert "hermes" not in payload


def test_system_status_does_not_claim_database_connection_after_probe_failure():
    db = Mock()
    db.execute.side_effect = OperationalError("SELECT 1", {}, Exception("offline"))

    payload = AdminService(db).get_system_status(settings)

    assert payload["database"] == {"status": "unavailable"}
    db.rollback.assert_called_once_with()


def test_admin_system_status_requires_authentication(anonymous_client):
    response = anonymous_client.get("/admin/api/system-status")

    assert response.status_code == 401
