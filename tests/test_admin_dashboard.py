import re

from fastapi.testclient import TestClient

from app.config import settings


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": settings.admin_api_key}


def test_admin_layout_keeps_sidebar_visible_on_desktop(
    anonymous_client: TestClient,
):
    response = anonymous_client.get("/admin", headers=_admin_headers())

    assert response.status_code == 200
    sidebar = re.search(r"<aside\b(?P<attributes>[^>]*)>", response.text, flags=re.DOTALL)
    assert sidebar is not None
    attributes = sidebar.group("attributes")
    assert "sidebar" in attributes
    assert "x-show" not in attributes
    assert "lg:translate-x-0" in attributes


def test_dashboard_does_not_render_actions_card(anonymous_client: TestClient):
    response = anonymous_client.get("/admin", headers=_admin_headers())

    assert response.status_code == 200
    assert "Ações Rápidas" not in response.text


