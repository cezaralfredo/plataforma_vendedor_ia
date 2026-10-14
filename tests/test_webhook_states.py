from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.models.webhook_event import WebhookEvent
from tests.seed import seed_appointment, seed_data, seed_payment


def _post_webhook(client: TestClient, payload: dict):
    return client.post(
        "/webhooks/asaas",
        json=payload,
        headers={"asaas-access-token": settings.asaas_webhook_token},
    )


def _payload(event_id: str, event: str, payment_id: str) -> dict:
    return {
        "id": event_id,
        "event": event,
        "payment": {"id": payment_id},
    }


def test_webhook_deduplicates_by_provider_event_id(
    client: TestClient,
    db_session: Session,
):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    appointment.expires_at = datetime.now() + timedelta(hours=1)
    payment = seed_payment(db_session, appointment)
    payload = _payload("evt_1", "PAYMENT_RECEIVED", payment.asaas_payment_id)

    assert _post_webhook(client, payload).json()["status"] == "ok"
    duplicate = _post_webhook(client, payload).json()

    assert duplicate["reason"] == "duplicate"
    events = db_session.query(WebhookEvent).all()
    assert [event.provider_event_id for event in events] == ["evt_1"]


def test_different_events_of_same_type_are_recorded(
    client: TestClient,
    db_session: Session,
):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    appointment.expires_at = datetime.now() + timedelta(hours=1)
    payment = seed_payment(db_session, appointment)

    first = _post_webhook(
        client,
        _payload("evt_1", "PAYMENT_CONFIRMED", payment.asaas_payment_id),
    )
    second = _post_webhook(
        client,
        _payload("evt_2", "PAYMENT_CONFIRMED", payment.asaas_payment_id),
    )

    assert first.json()["status"] == "ok"
    assert second.json()["status"] == "ok"
    assert db_session.query(WebhookEvent).count() == 2


def test_late_payment_does_not_reactivate_cancelled_appointment(
    client: TestClient,
    db_session: Session,
):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    appointment.status = "cancelled"
    payment = seed_payment(db_session, appointment)

    response = _post_webhook(
        client,
        _payload("evt_late", "PAYMENT_RECEIVED", payment.asaas_payment_id),
    )

    assert response.status_code == 200
    db_session.refresh(appointment)
    db_session.refresh(payment)
    assert payment.status == "received"
    assert appointment.status == "cancelled"


def test_payment_does_not_reactivate_expired_appointment(
    client: TestClient,
    db_session: Session,
):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    appointment.expires_at = datetime.now() - timedelta(minutes=1)
    payment = seed_payment(db_session, appointment)

    _post_webhook(
        client,
        _payload("evt_expired", "PAYMENT_RECEIVED", payment.asaas_payment_id),
    )

    db_session.refresh(appointment)
    assert appointment.status == "awaiting_payment"


def test_unknown_event_is_recorded(client: TestClient, db_session: Session):
    response = _post_webhook(
        client,
        {"id": "evt_unknown", "event": "PAYMENT_NEW_EVENT", "payment": {}},
    )

    assert response.status_code == 200
    assert db_session.query(WebhookEvent).filter_by(
        provider_event_id="evt_unknown"
    ).one()
