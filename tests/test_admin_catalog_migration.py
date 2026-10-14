from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.professional import Professional
from app.models.professional_service import ProfessionalService
from tests.seed import seed_data


def test_professional_service_defaults_commission_to_ten_percent(
    db_session: Session,
):
    """Detects a missing safe default when an admin associates a service."""
    entities = seed_data(db_session)
    another_professional = Professional(name="Outra profissional", active=True)
    db_session.add(another_professional)
    db_session.flush()

    offering = ProfessionalService(
        professional_id=another_professional.id,
        service_id=entities["service"].id,
    )
    db_session.add(offering)
    db_session.commit()

    assert offering.commission_percent == Decimal("10.00")


def test_appointment_keeps_commercial_snapshot_after_offering_changes(
    db_session: Session,
):
    """Detects historical financial data being changed by later catalog edits."""
    entities = seed_data(db_session)
    offering = (
        db_session.query(ProfessionalService)
        .filter_by(
            professional_id=entities["professional"].id,
            service_id=entities["service"].id,
        )
        .one()
    )
    entities["service"].price_cents = 12500
    entities["service"].duration_minutes = 60
    offering.commission_percent = Decimal("10.00")
    db_session.commit()

    appointment = Appointment(
        user_id=entities["user"].id,
        professional_id=entities["professional"].id,
        service_id=entities["service"].id,
        start_time=datetime(2026, 9, 10, 9, 0, tzinfo=UTC),
        end_time=datetime(2026, 9, 10, 10, 0, tzinfo=UTC),
        status="confirmed",
        service_price_cents=entities["service"].price_cents,
        service_duration_minutes=entities["service"].duration_minutes,
        professional_commission_percent=offering.commission_percent,
    )
    db_session.add(appointment)
    db_session.commit()

    entities["service"].price_cents = 20000
    offering.commission_percent = Decimal("25.00")
    db_session.commit()
    db_session.refresh(appointment)

    assert appointment.service_price_cents == 12500
    assert appointment.service_duration_minutes == 60
    assert appointment.professional_commission_percent == Decimal("10.00")
