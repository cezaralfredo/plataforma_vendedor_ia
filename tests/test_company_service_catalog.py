from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.payment import Payment
from app.models.professional import Professional
from app.models.professional_service import ProfessionalService
from app.models.service import Service
from app.schemas.professional_service import ProfessionalServiceCreate
from app.schemas.service import ServiceCreate
from app.services.professional_service_offering_service import (
    ProfessionalOfferingService,
)
from app.services.service_service import ServiceCatalogService
from tests.seed import seed_data


def test_appointment_snapshots_company_terms_and_assignment_commission(
    client, db_session
):
    entities = seed_data(db_session)
    service = entities["service"]
    assignment = service.professional_offerings[0]
    service.price_cents = 12345
    service.duration_minutes = 45
    assignment.commission_percent = "25.00"
    db_session.commit()

    response = client.post(
        "/api/appointments",
        json={
            "user_id": entities["user"].id,
            "professional_id": entities["professional"].id,
            "service_id": service.id,
            "start_time": "2026-07-30T09:00:00",
            "end_time": "2026-07-30T09:45:00",
        },
    )

    assert response.status_code == 201
    appointment = db_session.get(Appointment, response.json()["id"])
    assert appointment.service_price_cents == 12345
    assert appointment.service_duration_minutes == 45
    assert str(appointment.professional_commission_percent) == "25.00"


def test_company_owns_service_terms_and_professional_link_owns_commission(
    db_session: Session,
):
    """Moving commercial terms back to a professional must break this contract."""
    service = Service(
        name="Corte feminino",
        description="Corte personalizado",
        category="Cabelo",
        duration_minutes=60,
        price_cents=9000,
        active=True,
    )
    professional = Professional(name="Ana", active=True)
    db_session.add_all([service, professional])
    db_session.flush()

    assignment = ProfessionalService(
        professional_id=professional.id,
        service_id=service.id,
    )
    db_session.add(assignment)
    db_session.commit()

    assert service.price_cents == 9000
    assert service.duration_minutes == 60
    assert assignment.commission_percent == Decimal("10.00")
    assert not hasattr(Service, "professional_id")
    assert not hasattr(ProfessionalService, "price_cents")
    assert not hasattr(ProfessionalService, "duration_minutes")


def test_catalog_and_assignment_contracts_keep_their_responsibilities_separate():
    """Adding professional commercial terms back to assignments must break this contract."""
    service = ServiceCreate(
        name="Corte feminino",
        duration_minutes=60,
        price_cents=9000,
    )
    assignment = ProfessionalServiceCreate(service_id=7)

    assert service.price_cents == 9000
    assert service.duration_minutes == 60
    assert not hasattr(service, "professional_id")
    assert assignment.commission_percent == Decimal("10.00")
    assert not hasattr(assignment, "price_cents")
    assert not hasattr(assignment, "duration_minutes")


def test_assigning_professional_cannot_override_company_price_or_duration(
    db_session: Session,
):
    """Accepting per-professional price or duration must break this contract."""
    service = Service(
        name="Escova",
        duration_minutes=45,
        price_cents=7000,
        active=True,
    )
    professional = Professional(name="Bia", active=True)
    db_session.add_all([service, professional])
    db_session.commit()

    assignment = ProfessionalOfferingService(db_session).create_or_update(
        professional_id=professional.id,
        service_id=service.id,
        commission_percent=Decimal("25.00"),
    )

    assert assignment.service.price_cents == 7000
    assert assignment.service.duration_minutes == 45
    assert assignment.commission_percent == Decimal("25.00")


def test_company_creates_catalog_service_without_choosing_professional(
    client: TestClient,
):
    """Requiring a professional while creating a catalog item must break this API."""
    response = client.post(
        "/api/services",
        json={
            "name": "Coloração",
            "description": "Coloração completa",
            "category": "Cabelo",
            "duration_minutes": 120,
            "price_cents": 18000,
        },
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Coloração"
    assert response.json()["price_cents"] == 18000


def test_public_api_manages_professional_service_assignment(client, db_session):
    entities = seed_data(db_session)
    professional = Professional(name="Nova profissional", active=True)
    db_session.add(professional)
    db_session.commit()

    created = client.post(
        f"/api/professionals/{professional.id}/services",
        json={"service_id": entities["service"].id, "active": False},
    )
    assert created.status_code == 201
    assert created.json()["commission_percent"] == "10.00"
    assert created.json()["active"] is False

    updated = client.put(
        f"/api/professionals/{professional.id}/services/{entities['service'].id}",
        json={"commission_percent": "22.50", "active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["commission_percent"] == "22.50"
    assert updated.json()["active"] is False

    deleted = client.delete(
        f"/api/professionals/{professional.id}/services/{entities['service'].id}"
    )
    assert deleted.status_code == 204


def test_public_api_rejects_reactivating_assignment_for_inactive_professional(
    client, db_session
):
    entities = seed_data(db_session)
    entities["professional"].active = False
    assignment = entities["service"].professional_offerings[0]
    assignment.active = False
    db_session.commit()

    response = client.put(
        f"/api/professionals/{entities['professional'].id}/services/{entities['service'].id}",
        json={"active": True},
    )

    assert response.status_code == 409
    assert assignment.active is False


def test_expired_unpaid_service_history_is_deleted_instead_of_archived(
    db_session: Session,
):
    """Treating a non-sale as permanent financial history must break this rule."""
    entities = seed_data(db_session)
    appointment = Appointment(
        user_id=entities["user"].id,
        professional_id=entities["professional"].id,
        service_id=entities["service"].id,
        start_time=datetime.now(UTC) + timedelta(days=1),
        end_time=datetime.now(UTC) + timedelta(days=1, hours=1),
        status="cancelled",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
        service_price_cents=entities["service"].price_cents,
        service_duration_minutes=entities["service"].duration_minutes,
        professional_commission_percent=Decimal("10.00"),
    )
    db_session.add(appointment)
    db_session.flush()
    db_session.add(
        Payment(
            appointment_id=appointment.id,
            amount_cents=entities["service"].price_cents,
            billing_type="pix",
            status="overdue",
        )
    )
    db_session.commit()
    service_id = entities["service"].id
    appointment_id = appointment.id

    outcome = ServiceCatalogService(db_session).archive_or_delete(service_id)

    assert outcome == "deleted"
    assert db_session.get(Service, service_id) is None
    assert db_session.get(Appointment, appointment_id) is None


def test_public_delete_removes_cancelled_unpaid_service_history(client, db_session):
    entities = seed_data(db_session)
    appointment = Appointment(
        user_id=entities["user"].id,
        professional_id=entities["professional"].id,
        service_id=entities["service"].id,
        start_time=datetime(2026, 8, 1, 9),
        end_time=datetime(2026, 8, 1, 10),
        status="cancelled",
    )
    db_session.add(appointment)
    db_session.flush()
    db_session.add(
        Payment(
            appointment_id=appointment.id,
            amount_cents=entities["service"].price_cents,
            billing_type="pix",
            status="overdue",
        )
    )
    service_id = entities["service"].id
    appointment_id = appointment.id
    db_session.commit()

    response = client.delete(f"/api/services/{service_id}")

    assert response.status_code == 204
    assert db_session.get(Service, service_id) is None
    assert db_session.get(Appointment, appointment_id) is None


def test_public_delete_rejects_service_with_paid_history(client, db_session):
    entities = seed_data(db_session)
    appointment = Appointment(
        user_id=entities["user"].id,
        professional_id=entities["professional"].id,
        service_id=entities["service"].id,
        start_time=datetime(2026, 8, 1, 9),
        end_time=datetime(2026, 8, 1, 10),
        status="confirmed",
    )
    db_session.add(appointment)
    db_session.flush()
    db_session.add(
        Payment(
            appointment_id=appointment.id,
            amount_cents=entities["service"].price_cents,
            billing_type="pix",
            status="received",
        )
    )
    service_id = entities["service"].id
    db_session.commit()

    response = client.delete(f"/api/services/{service_id}")

    assert response.status_code == 409
    assert "desative" in response.json()["detail"].lower()
    assert db_session.get(Service, service_id).active is True


def test_catalog_management_defines_company_price_and_duration(
    db_session: Session,
):
    """Creating a catalog record without company terms must break management."""
    service = ServiceCatalogService(db_session).create(
        name="Manicure",
        description="Manicure completa",
        category="Unhas",
        duration_minutes=50,
        price_cents=6500,
    )

    assert service.duration_minutes == 50
    assert service.price_cents == 6500
