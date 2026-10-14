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
