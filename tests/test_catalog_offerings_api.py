from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.models.professional import Professional
from app.models.professional_service import ProfessionalService
from app.models.service import Service


def _mcp_call(client: TestClient, name: str, arguments: dict):
    return client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {"name": name, "arguments": arguments},
        },
        headers={"Authorization": f"Bearer {settings.api_key}"},
    )


def _create_catalog_offerings(db_session: Session) -> tuple[Service, Professional]:
    service = Service(
        name="Massagem relaxante",
        category="Bem-estar",
        price_cents=15000,
        duration_minutes=60,
        active=True,
    )
    professional = Professional(name="Ana Lima", phone="11999999999", active=True)
    inactive_professional = Professional(
        name="Bruno Lima", phone="11999999998", active=False
    )
    db_session.add_all([service, professional, inactive_professional])
    db_session.flush()
    db_session.add_all(
        [
            ProfessionalService(
                professional_id=professional.id,
                service_id=service.id,
                commission_percent="10.00",
                active=True,
            ),
            ProfessionalService(
                professional_id=inactive_professional.id,
                service_id=service.id,
                commission_percent="25.00",
                active=True,
            ),
        ]
    )
    db_session.commit()
    return service, professional


def test_api_lists_company_catalog_once_including_unassigned_services(
    client: TestClient, db_session: Session
):
    service, _professional = _create_catalog_offerings(db_session)
    unassigned = Service(
        name="Drenagem",
        price_cents=12000,
        duration_minutes=50,
        active=True,
    )
    db_session.add(unassigned)
    db_session.commit()

    response = client.get("/api/services")

    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {service.id, unassigned.id}
    assert sum(item["id"] == service.id for item in response.json()) == 1


def test_mcp_lists_catalog_service_using_active_offering_values(
    client: TestClient, db_session: Session
):
    _create_catalog_offerings(db_session)

    response = _mcp_call(client, "listar_servicos", {})

    assert response.status_code == 200
    result = response.json()["result"]
    assert result.get("isError") is not True
    text = result["content"][0]["text"]
    assert "Massagem relaxante" in text
    assert "R$ 150,00" in text
    assert "(60min)" in text
    assert "Ana Lima" in text
    assert "Bruno Lima" not in text


def test_api_uses_company_terms_and_professional_commission(
    client: TestClient, db_session: Session
):
    service, first_professional = _create_catalog_offerings(db_session)
    second_professional = Professional(
        name="Carla Lima", phone="11999999997", active=True
    )
    db_session.add(second_professional)
    db_session.flush()
    db_session.add(
        ProfessionalService(
            professional_id=second_professional.id,
            service_id=service.id,
            commission_percent="25.00",
            active=True,
        )
    )
    db_session.commit()

    response = client.get(f"/api/professionals/{first_professional.id}/services")

    assert response.status_code == 200
    assert response.json()[0]["commission_percent"] == "10.00"

    second_response = client.get(
        f"/api/professionals/{second_professional.id}/services"
    )
    assert second_response.status_code == 200
    assert second_response.json()[0]["commission_percent"] == "25.00"
