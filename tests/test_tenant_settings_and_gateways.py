from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from app.schemas.appointment import AppointmentCreate
from app.schemas.company_settings import CompanySettingsUpdate
from app.services.appointment_service import AppointmentService
from app.services.company_settings_service import CompanySettingsService
from app.services.payment_gateways import (
    AsaasPaymentGateway,
    ManualPaymentGateway,
    get_payment_gateway,
)
from tests.seed import seed_data


def test_company_settings_get_or_create_default(db_session: Session):
    service = CompanySettingsService(db_session)
    settings = service.get_or_create_default()

    assert settings.id is not None
    assert settings.company_name == "Minha Empresa"
    assert settings.payment_required is True
    assert settings.default_gateway == "asaas"
    assert settings.whatsapp_provider == "evolution"
    assert settings.tone == "casual"
    assert settings.commission_model == "percentage"
    assert settings.human_support_phone is None
    assert settings.human_support_name == "Equipe de Atendimento"


def test_company_settings_update(db_session: Session):
    service = CompanySettingsService(db_session)
    updated = service.update(
        CompanySettingsUpdate(
            company_name="Barbearia VIP",
            payment_required=False,
            default_gateway="manual",
            whatsapp_provider="meta",
            meta_phone_number_id="1029384756",
            tone="formal",
            human_support_phone="5585999991234",
            human_support_name="Plantão VIP",
            human_support_message="Transferindo agora para nosso especialista VIP.",
        )
    )

    assert updated.company_name == "Barbearia VIP"
    assert updated.payment_required is False
    assert updated.default_gateway == "manual"
    assert updated.whatsapp_provider == "meta"
    assert updated.meta_phone_number_id == "1029384756"
    assert updated.tone == "formal"
    assert updated.human_support_phone == "5585999991234"
    assert updated.human_support_name == "Plantão VIP"
    assert updated.human_support_message == "Transferindo agora para nosso especialista VIP."


def test_payment_gateway_factory():
    asaas_gw = get_payment_gateway("asaas", {"api_key": "test-key"})
    assert isinstance(asaas_gw, AsaasPaymentGateway)

    manual_gw = get_payment_gateway("manual")
    assert isinstance(manual_gw, ManualPaymentGateway)

    counter_gw = get_payment_gateway("in_person")
    assert isinstance(counter_gw, ManualPaymentGateway)


@pytest.mark.asyncio
async def test_manual_payment_gateway_charge_and_status():
    gateway = ManualPaymentGateway()
    res = await gateway.create_charge(
        appointment_id=42,
        amount_cents=5000,
        customer_info={"name": "Cliente Teste"},
    )

    assert res["status"] == "confirmed"
    assert res["gateway_payment_id"] == "manual:42"
    assert res["invoice_url"] is None

    status_res = await gateway.check_status("manual:42")
    assert status_res["status"] == "confirmed"


def test_appointment_creation_when_payment_is_mandatory(db_session: Session):
    entities = seed_data(db_session)
    settings_service = CompanySettingsService(db_session)
    settings_service.update(CompanySettingsUpdate(payment_required=True))

    service = AppointmentService(db_session)
    appointment = service.create(
        AppointmentCreate(
            user_id=entities["user"].id,
            start_time=datetime(2026, 7, 30, 10, 0, 0),
            end_time=datetime(2026, 7, 30, 11, 0, 0),
        )
    )

    assert appointment.status == "pending"
    assert appointment.expires_at is not None


def test_appointment_creation_when_payment_is_optional(db_session: Session):
    entities = seed_data(db_session)
    settings_service = CompanySettingsService(db_session)
    settings_service.update(CompanySettingsUpdate(payment_required=False))

    service = AppointmentService(db_session)
    appointment = service.create(
        AppointmentCreate(
            user_id=entities["user"].id,
            start_time=datetime(2026, 7, 30, 14, 0, 0),
            end_time=datetime(2026, 7, 30, 15, 0, 0),
        )
    )

    assert appointment.status == "confirmed"
    assert appointment.expires_at is None
