import httpx
from fastapi.testclient import TestClient

import mcp_gateway.main as gateway


class _HealthyUpstream:
    async def get(self, path: str) -> httpx.Response:
        assert path == "/ready"
        return httpx.Response(
            200,
            request=httpx.Request("GET", "http://api:8000/ready"),
        )


class _UnavailableUpstream:
    async def get(self, path: str) -> httpx.Response:
        assert path == "/ready"
        raise httpx.ConnectError("upstream unavailable")


def test_gateway_ready_checks_api_upstream(monkeypatch):
    monkeypatch.setattr(gateway, "http_client", _HealthyUpstream())

    response = TestClient(gateway.app).get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_gateway_ready_returns_safe_error_when_upstream_is_unavailable(monkeypatch):
    monkeypatch.setattr(gateway, "http_client", _UnavailableUpstream())

    response = TestClient(gateway.app).get("/ready")

    assert response.status_code == 502
    assert response.json() == {"detail": "API indisponível"}


def test_gateway_mcp_fails_closed_when_key_not_configured(monkeypatch):
    monkeypatch.setattr(gateway.settings, "gateway_key", "")

    response = TestClient(gateway.app).post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )

    assert response.status_code == 503


def test_gateway_mcp_rejects_invalid_key(monkeypatch):
    monkeypatch.setattr(gateway.settings, "gateway_key", "super-secret-gateway-key")

    response = TestClient(gateway.app).post(
        "/mcp",
        headers={"X-Gateway-Key": "wrong-key"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )

    assert response.status_code == 401
