import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.mcp.tools import handle_tool_call
from app.models.notification_log import NotificationLog
from app.services.asaas_client import AsaasClient
from app.services.payment_service import PaymentService
from tests.seed import seed_appointment, seed_data, seed_payment


def test_asaas_client_reuses_http_client_and_has_lower_timeouts():
    client = AsaasClient()
    assert client.timeout.connect == 5.0
    assert client.timeout.read == 15.0

    http_client_1 = client._get_client()
    http_client_2 = client._get_client()
    assert http_client_1 is http_client_2
    assert not http_client_1.is_closed

    asyncio.run(client.aclose())
    assert http_client_1.is_closed


def test_ensure_asaas_customer_does_not_call_update_for_existing_customer(db_session: Session):
    entities = seed_data(db_session)
    user = entities["user"]
    user.asaas_customer_id = "cus_already_exists"
    user.cpf_cnpj = "12345678901"
    db_session.commit()

    service = PaymentService(db_session)
    service.asaas.update_customer = AsyncMock()

    customer_id = asyncio.run(service.ensure_asaas_customer(user.id))
    assert customer_id == "cus_already_exists"
    service.asaas.update_customer.assert_not_awaited()


def test_create_charge_fast_path_returns_existing_active_payment(db_session: Session):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    payment = seed_payment(db_session, appointment)
    payment.status = "pending"
    db_session.commit()

    service = PaymentService(db_session)
    service.asaas.list_payments = AsyncMock()
    service.asaas.create_payment = AsyncMock()

    returned_payment = asyncio.run(service.create_charge(appointment.id, "pix"))
    assert returned_payment.id == payment.id
    service.asaas.list_payments.assert_not_awaited()
    service.asaas.create_payment.assert_not_awaited()


def test_list_unnotified_confirmed_finds_confirmed_appointments_awaiting_notice(
    db_session: Session,
):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    appointment.status = "confirmed"
    appointment.notified_at = None
    db_session.commit()

    service = PaymentService(db_session)
    unnotified = service.list_unnotified_confirmed()
    assert len(unnotified) == 1
    assert unnotified[0].id == appointment.id


def test_webhook_creates_notification_log_on_payment_confirmation(
    client: TestClient,
    db_session: Session,
):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    appointment.status = "awaiting_payment"
    appointment.expires_at = datetime.now(UTC) + timedelta(hours=1)
    payment = seed_payment(db_session, appointment)
    payment.status = "pending"
    db_session.commit()

    response = client.post(
        "/webhooks/asaas",
        json={
            "id": "evt_conf_notif_1",
            "event": "PAYMENT_RECEIVED",
            "payment": {"id": payment.asaas_payment_id},
        },
        headers={"asaas-access-token": settings.asaas_webhook_token},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    db_session.refresh(appointment)
    assert appointment.status == "confirmed"

    logs = (
        db_session.query(NotificationLog)
        .filter(NotificationLog.appointment_id == appointment.id)
        .all()
    )
    assert len(logs) >= 1
    assert logs[0].type == "payment_received"


def test_mcp_tools_listar_pendentes_e_marcar_notificado(db_session: Session):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    appointment.status = "confirmed"
    appointment.notified_at = None
    db_session.commit()

    # 1. Listar pendentes
    res_list = asyncio.run(handle_tool_call("listar_pendentes_notificacao", {}, db_session))
    text_list = res_list["content"][0]["text"]
    assert f"Agendamento #{appointment.id}" in text_list
    assert "aguardando notificação" in text_list

    # 2. A confirmação manual não pode criar um falso positivo de entrega.
    res_mark = asyncio.run(
        handle_tool_call("marcar_notificado", {"appointment_id": appointment.id}, db_session)
    )
    text_mark = res_mark["content"][0]["text"]
    assert "registrada automaticamente" in text_mark

    db_session.refresh(appointment)
    assert appointment.notified_at is None

    # Verifica se registrou NotificationLog com type='confirmation'
    log = (
        db_session.query(NotificationLog)
        .filter(
            NotificationLog.appointment_id == appointment.id,
            NotificationLog.type == "confirmation",
        )
        .first()
    )
    assert log is None

    # 3. A pendência permanece até a confirmação do provedor WhatsApp.
    res_empty = asyncio.run(handle_tool_call("listar_pendentes_notificacao", {}, db_session))
    assert f"Agendamento #{appointment.id}" in res_empty["content"][0]["text"]
