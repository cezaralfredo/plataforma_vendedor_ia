from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.seed import seed_appointment, seed_data, seed_payment


def test_awaiting_payment_expires_and_releases_slot(
    client: TestClient,
    db_session: Session,
):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    appointment.expires_at = datetime.now() - timedelta(minutes=1)
    db_session.commit()

    response = client.get(
        f"/api/availability/slots/{appointment.professional_id}/{appointment.service_id}",
        params={"date": appointment.start_time.date().isoformat()},
    )

    assert response.status_code == 200
    assert any(
        slot["start"].startswith(appointment.start_time.strftime("%Y-%m-%dT%H:%M"))
        for slot in response.json()
    )
    db_session.refresh(appointment)
    assert appointment.status == "cancelled"


def test_completed_appointment_cannot_be_cancelled(
    client: TestClient,
    db_session: Session,
):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    appointment.status = "completed"
    db_session.commit()

    response = client.post(f"/api/appointments/{appointment.id}/cancel")

    assert response.status_code == 409


def test_confirm_is_idempotent(client: TestClient, db_session: Session):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    appointment.status = "confirmed"
    db_session.commit()

    response = client.post(f"/api/appointments/{appointment.id}/confirm")

    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"


def test_pending_appointment_cannot_be_confirmed_without_received_payment(
    client: TestClient, db_session: Session
):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    appointment.status = "pending"
    db_session.commit()

    response = client.post(f"/api/appointments/{appointment.id}/confirm")

    assert response.status_code == 409
    assert "pagamento" in response.json()["detail"].lower()


def test_pending_appointment_can_be_confirmed_after_received_payment(
    client: TestClient, db_session: Session
):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    appointment.status = "pending"
    payment = seed_payment(db_session, appointment)
    payment.status = "received"
    db_session.commit()

    response = client.post(f"/api/appointments/{appointment.id}/confirm")

    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"
