from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.repositories.appointment_repo import AppointmentRepository
from tests.seed import seed_data


class _ConstraintDiagnostic:
    constraint_name = "exclude_professional_overlapping_appointments"


class _ExclusionViolation(Exception):
    diag = _ConstraintDiagnostic()


def test_exclusion_conflict_becomes_http_409(
    client: TestClient,
    db_session: Session,
    monkeypatch,
):
    entities = seed_data(db_session)

    def raise_exclusion(_self, **_kwargs):
        raise IntegrityError("insert", {}, _ExclusionViolation())

    monkeypatch.setattr(AppointmentRepository, "create", raise_exclusion)
    response = client.post(
        "/api/appointments",
        json={
            "user_id": entities["user"].id,
            "professional_id": entities["professional"].id,
            "service_id": entities["service"].id,
            "start_time": "2026-07-30T09:00:00",
            "end_time": "2026-07-30T10:00:00",
        },
    )

    assert response.status_code == 409
    assert "reserva" in response.json()["detail"].lower()


def test_appointment_model_declares_postgres_exclusion_constraint():
    names = {constraint.name for constraint in Appointment.__table__.constraints}
    assert "exclude_professional_overlapping_appointments" in names
    assert "check_appointment_interval" in names


def test_overlapping_insert_is_rejected_by_postgres(db_session: Session):
    if db_session.bind.dialect.name != "postgresql":
        return
    entities = seed_data(db_session)
    first = Appointment(
        user_id=entities["user"].id,
        professional_id=entities["professional"].id,
        service_id=entities["service"].id,
        start_time=datetime.fromisoformat("2026-08-26T09:00:00-03:00"),
        end_time=datetime.fromisoformat("2026-08-26T10:00:00-03:00"),
        status="confirmed",
    )
    second = Appointment(
        user_id=entities["user"].id,
        professional_id=entities["professional"].id,
        service_id=entities["service"].id,
        start_time=datetime.fromisoformat("2026-08-26T09:30:00-03:00"),
        end_time=datetime.fromisoformat("2026-08-26T10:30:00-03:00"),
        status="confirmed",
    )
    db_session.add(first)
    db_session.commit()
    db_session.add(second)
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        return
    raise AssertionError("PostgreSQL accepted overlapping active appointments")
