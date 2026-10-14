from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.professional import Professional
from app.schemas.appointment import AppointmentCreate
from app.services.appointment_service import AppointmentService
from app.services.professional_service import ProfessionalManagementService
from app.services.professional_service_offering_service import ProfessionalOfferingService
from app.services.service_service import ServiceCatalogService
from tests.seed import seed_appointment, seed_data


def test_service_with_appointment_is_archived_not_deleted(db_session: Session):
    entities = seed_data(db_session)
    seed_appointment(db_session, entities)

    outcome = ServiceCatalogService(db_session).archive_or_delete(
        entities["service"].id
    )

    assert outcome == "archived"
    assert entities["service"].active is False


def test_professional_without_history_is_deleted(db_session: Session):
    professional = Professional(name="Sem histórico", active=True)
    db_session.add(professional)
    db_session.commit()

    outcome = ProfessionalManagementService(db_session).archive_or_delete(
        professional.id
    )

    assert outcome == "deleted"
    assert db_session.get(Professional, professional.id) is None


def test_appointment_uses_active_offering_and_keeps_its_commercial_snapshot(
    db_session: Session,
):
    entities = seed_data(db_session)
    entities["service"].price_cents = 7500
    entities["service"].duration_minutes = 60
    db_session.commit()
    offering = ProfessionalOfferingService(db_session).create_or_update(
        professional_id=entities["professional"].id,
        service_id=entities["service"].id,
        commission_percent=Decimal("17.50"),
    )

    appointment = AppointmentService(db_session).create(
        AppointmentCreate(
            user_id=entities["user"].id,
            professional_id=entities["professional"].id,
            service_id=entities["service"].id,
            start_time=datetime(2026, 7, 30, 10, 0),
            end_time=datetime(2026, 7, 30, 11, 0),
        )
    )

    assert appointment.service_price_cents == 7500
    assert appointment.service_duration_minutes == 60
    assert appointment.professional_commission_percent == Decimal("17.50")

    offering.active = False
    db_session.commit()

    with pytest.raises(ValueError, match="Serviço indisponível"):
        AppointmentService(db_session).create(
            AppointmentCreate(
                user_id=entities["user"].id,
                professional_id=entities["professional"].id,
                service_id=entities["service"].id,
                start_time=datetime(2026, 7, 30, 11, 0),
                end_time=datetime(2026, 7, 30, 12, 0),
            )
        )
