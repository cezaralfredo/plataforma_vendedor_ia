
import json
from html.parser import HTMLParser

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.models.professional import Professional
from app.models.professional_service import ProfessionalService
from app.models.service import Service


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": settings.admin_api_key}


class _ServicesBootstrapParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.x_data: str | None = None
        self.dashboard_json = ""

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if "x-data" in attributes:
            self.x_data = attributes["x-data"]
        if attributes.get("id") == "service-dashboard-data":
            self.dashboard_json = attributes.get("data-dashboard") or ""


def test_services_page_is_in_admin_navigation(anonymous_client: TestClient):
    response = anonymous_client.get("/admin/services", headers=_admin_headers())

    assert response.status_code == 200
    assert "Gestão de Serviços" in response.text
    assert 'href="/admin/services"' in response.text


def test_admin_uses_bundled_alpine_runtime(anonymous_client: TestClient):
    """The admin must remain interactive when third-party CDNs are unavailable."""
    response = anonymous_client.get("/admin/services", headers=_admin_headers())

    assert response.status_code == 200
    assert 'src="/admin/static/vendor/alpine.min.js"' in response.text
    assert "cdn.jsdelivr.net/npm/alpinejs" not in response.text

    runtime = anonymous_client.get("/admin/static/vendor/alpine.min.js")
    assert runtime.status_code == 200
    assert "Alpine" in runtime.text


def test_services_dashboard_data_does_not_break_alpine_expression(
    anonymous_client: TestClient, db_session: Session
):
    """Catches JSON quotes truncating the x-data attribute in the browser."""
    db_session.add(
        Service(
            name='Corte "Premium"',
            category="Cabelos",
            price_cents=12000,
            duration_minutes=60,
            active=True,
        )
    )
    db_session.commit()

    response = anonymous_client.get("/admin/services", headers=_admin_headers())

    parser = _ServicesBootstrapParser()
    parser.feed(response.text)
    assert parser.x_data == "serviceCatalog()"
    dashboard = json.loads(parser.dashboard_json)
    assert dashboard["services"][0]["name"] == 'Corte "Premium"'


def test_services_dashboard_reports_catalog_health(
    anonymous_client: TestClient, db_session: Session
):
    """Catches a dashboard that hides blank, duplicate, or unassigned services."""
    professional = Professional(name="Profissional", phone="11999999999")
    active_service = Service(name="Corte", category="Cabelos", price_cents=9000, duration_minutes=45, active=True)
    duplicate_service = Service(name=" corte ", category="Cabelos", price_cents=9000, duration_minutes=45, active=True)
    blank_service = Service(name="   ", price_cents=1000, duration_minutes=30, active=True)
    archived_service = Service(name="Serviço antigo", price_cents=1000, duration_minutes=30, active=False)
    db_session.add_all(
        [professional, active_service, duplicate_service, blank_service, archived_service]
    )
    db_session.commit()
    db_session.add(
        ProfessionalService(
            professional_id=professional.id,
            service_id=active_service.id,
        )
    )
    db_session.commit()

    response = anonymous_client.get(
        "/admin/api/services/dashboard", headers=_admin_headers()
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"] == {
        "active_services": 3,
        "active_offerings": 1,
        "professionals_with_offerings": 1,
        "services_without_professionals": 2,
        "inconsistencies": 2,
    }
    assert payload["issues"] == [
        {
            "kind": "unnamed",
            "label": "Serviço sem denominação",
            "service_ids": [blank_service.id],
        },
        {
            "kind": "duplicate",
            "label": "Corte",
            "service_ids": [active_service.id, duplicate_service.id],
        },
    ]


def test_services_dashboard_distinguishes_similar_names_from_exact_duplicates(
    anonymous_client: TestClient, db_session: Session
):
    masculine = Service(
        name="Corte de cabelo",
        category="Masculino",
        price_cents=5000,
        duration_minutes=30,
        active=True,
    )
    feminine = Service(
        name=" corte de cabelo ",
        category="Feminino",
        price_cents=9000,
        duration_minutes=60,
        active=True,
    )
    db_session.add_all([masculine, feminine])
    db_session.commit()

    response = anonymous_client.get(
        "/admin/api/services/dashboard", headers=_admin_headers()
    )

    assert response.status_code == 200
    assert response.json()["issues"] == [
        {
            "kind": "similar_name",
            "label": "Corte de cabelo",
            "service_ids": [masculine.id, feminine.id],
        }
    ]


def test_services_dashboard_ignores_offerings_of_archived_professionals(
    anonymous_client: TestClient, db_session: Session
):
    """Catches catalog coverage that is not actually available for booking."""
    professional = Professional(
        name="Profissional arquivado", phone="11999999999", active=False
    )
    service = Service(name="Serviço sem cobertura", price_cents=9000, duration_minutes=45, active=True)
    db_session.add_all([professional, service])
    db_session.commit()
    db_session.add(
        ProfessionalService(
            professional_id=professional.id,
            service_id=service.id,
            active=True,
        )
    )
    db_session.commit()

    response = anonymous_client.get(
        "/admin/api/services/dashboard", headers=_admin_headers()
    )

    assert response.status_code == 200
    assert response.json()["metrics"] == {
        "active_services": 1,
        "active_offerings": 0,
        "professionals_with_offerings": 0,
        "services_without_professionals": 1,
        "inconsistencies": 0,
    }


def test_services_page_shows_catalog_overview(anonymous_client: TestClient):
    """Catches removal of the operational summary from the services page."""
    response = anonymous_client.get("/admin/services", headers=_admin_headers())

    assert response.status_code == 200
    assert "Visão do catálogo" in response.text
    assert "Serviços sem profissional" in response.text
    assert "Revisar inconsistências" in response.text
    assert "Preço da empresa" in response.text
    assert "Duração" in response.text


def test_admin_manages_shared_service_catalog(anonymous_client: TestClient):
    created = anonymous_client.post(
        "/admin/api/services",
        headers=_admin_headers(),
        json={
            "name": "Massagem relaxante",
            "description": "Sessão de bem-estar",
            "category": "Massagens",
            "price_cents": 15000,
            "duration_minutes": 60,
        },
    )

    assert created.status_code == 201
    service = created.json()
    assert service["name"] == "Massagem relaxante"
    assert service["active"] is True
    assert service["active_offerings_count"] == 0
    assert service["price_cents"] == 15000
    assert service["duration_minutes"] == 60

    updated = anonymous_client.put(
        f"/admin/api/services/{service['id']}",
        headers=_admin_headers(),
        json={"name": "Massagem terapêutica", "category": "Terapias", "price_cents": 18000, "duration_minutes": 75},
    )

    assert updated.status_code == 200
    assert updated.json()["name"] == "Massagem terapêutica"
    assert updated.json()["category"] == "Terapias"
    assert updated.json()["price_cents"] == 18000
    assert updated.json()["duration_minutes"] == 75


def test_deleting_catalog_service_without_history_removes_assignment_and_service(
    anonymous_client: TestClient, db_session: Session
):
    professional = Professional(name="Profissional", phone="11999999999")
    service = Service(name="Corte", category="Cabelos", price_cents=9000, duration_minutes=45, active=True)
    db_session.add_all([professional, service])
    db_session.commit()
    db_session.add(
        ProfessionalService(
            professional_id=professional.id,
            service_id=service.id,
        )
    )
    db_session.commit()

    deleted = anonymous_client.delete(
        f"/admin/api/services/{service.id}", headers=_admin_headers()
    )

    assert deleted.status_code == 200
    assert deleted.json() == {"outcome": "deleted"}
    assert db_session.get(Service, service.id) is None
