
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.admin.service import AdminService
from app.config import settings
from app.models.professional_service import ProfessionalService
from app.models.service import Service
from tests.seed import seed_data


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": settings.admin_api_key}


def test_admin_creates_offering_with_configurable_commission(
    anonymous_client: TestClient, db_session: Session
):
    entities = seed_data(db_session)

    response = anonymous_client.post(
        f"/admin/api/professionals/{entities['professional'].id}/services",
        headers=_admin_headers(),
        json={
            "service_id": entities["service"].id,
            "commission_percent": "17.50",
        },
    )

    assert response.status_code == 201
    assert response.json()["price_cents"] == entities["service"].price_cents
    assert response.json()["duration_minutes"] == entities["service"].duration_minutes
    assert response.json()["commission_percent"] == "17.50"


def test_admin_rejects_overlapping_availability(
    anonymous_client: TestClient, db_session: Session
):
    entities = seed_data(db_session)

    response = anonymous_client.post(
        f"/admin/api/professionals/{entities['professional'].id}/availability",
        headers=_admin_headers(),
        json={
            "day_of_week": 2,
            "start_time": "09:30",
            "end_time": "11:00",
        },
    )

    assert response.status_code == 409
    assert "sobrepõe" in response.json()["detail"]


def test_professional_edit_page_shows_management_sections(
    anonymous_client: TestClient, db_session: Session
):
    entities = seed_data(db_session)

    response = anonymous_client.get(
        f"/admin/professionals/{entities['professional'].id}/edit",
        headers=_admin_headers(),
    )

    assert response.status_code == 200
    assert "Horários de atendimento" in response.text
    assert "Serviços oferecidos" in response.text
    assert "Preço e duração são definidos pela empresa" in response.text


def test_professionals_page_links_to_management_ui(
    anonymous_client: TestClient, db_session: Session
):
    seed_data(db_session)

    response = anonymous_client.get("/admin/professionals", headers=_admin_headers())

    assert response.status_code == 200
    assert "/admin/professionals/new" in response.text
    assert "/admin/professionals/' + prof.id + '/edit" in response.text


def test_professional_summary_counts_active_shared_catalog_offerings(
    db_session: Session,
):
    entities = seed_data(db_session)
    service = Service(name="Serviço extra", price_cents=7000, duration_minutes=45, active=True)
    db_session.add(service)
    db_session.flush()
    db_session.add(
        ProfessionalService(
            professional_id=entities["professional"].id,
            service_id=service.id,
        )
    )
    db_session.commit()

    rows = AdminService(db_session).list_professionals()

    assert rows[0]["services_count"] == 3
