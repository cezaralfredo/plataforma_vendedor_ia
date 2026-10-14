import re

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.models.professional import Professional


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


def test_professionals_overview_api_limits_rows_without_changing_row_contract(
    anonymous_client: TestClient,
    db_session: Session,
):
    for index in range(6):
        db_session.add(
            Professional(
                name=f"Profissional {index + 1}",
                phone=f"+5511999999{index:03d}",
                active=True,
            )
        )
    db_session.commit()

    response = anonymous_client.get(
        "/admin/api/professionals?limit=5",
        headers=_admin_headers(),
    )

    assert response.status_code == 200
    professionals = response.json()
    assert len(professionals) == 5
    assert set(professionals[0]) >= {
        "id",
        "name",
        "active",
        "services_count",
        "appointments_today",
        "appointments_week",
        "revenue_month_cents",
    }
