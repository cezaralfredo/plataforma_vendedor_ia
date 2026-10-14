from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.admin.service import AdminService
from app.config import settings
from app.models.payment import Payment
from tests.seed import seed_appointment, seed_data


def test_appointment_list_returns_one_row_with_latest_payment(db_session: Session):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    old = Payment(
        appointment_id=appointment.id,
        asaas_payment_id="pay_old",
        amount_cents=5000,
        billing_type="pix",
        status="cancelled",
        created_at=datetime(2026, 8, 1),
        updated_at=datetime(2026, 8, 1),
    )
    latest = Payment(
        appointment_id=appointment.id,
        asaas_payment_id="pay_latest",
        amount_cents=5000,
        billing_type="pix",
        status="pending",
        created_at=datetime(2026, 8, 2),
        updated_at=datetime(2026, 8, 2),
    )
    db_session.add_all([old, latest])
    db_session.commit()

    rows, total = AdminService(db_session).list_appointments()

    assert total == 1
    assert len(rows) == 1
    assert rows[0]["payment_id"] == latest.id


def test_confirmed_payment_is_not_counted_pending(db_session: Session):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    db_session.add(
        Payment(
            appointment_id=appointment.id,
            asaas_payment_id="pay_confirmed",
            amount_cents=5000,
            billing_type="pix",
            status="confirmed",
        )
    )
    db_session.commit()
    assert AdminService(db_session).get_kpis()["payments_pending"] == 0


def test_admin_appointment_list_keeps_historical_service_price(db_session: Session):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    appointment.service_price_cents = 7500
    entities["service"].price_cents = 9900
    db_session.commit()

    rows, _ = AdminService(db_session).list_appointments()

    assert rows[0]["service_price_cents"] == 7500


def test_admin_appointment_detail_keeps_historical_service_terms(db_session: Session):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    appointment.service_price_cents = 7500
    appointment.service_duration_minutes = 75
    entities["service"].price_cents = 9900
    entities["service"].duration_minutes = 30
    db_session.commit()

    detail = AdminService(db_session).get_appointment_detail(appointment.id)

    assert detail["service"]["price_cents"] == 7500
    assert detail["service"]["duration_minutes"] == 75


def test_admin_rejects_zero_page(anonymous_client: TestClient):
    response = anonymous_client.get(
        "/admin/api/appointments?page=0",
        headers={"X-Admin-Key": settings.admin_api_key},
    )
    assert response.status_code == 422
