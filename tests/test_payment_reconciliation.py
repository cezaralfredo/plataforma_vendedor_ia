import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import Session

from app.services.asaas_client import AsaasUncertainResultError
from app.services.payment_service import AsaasReconciliationError, PaymentService
from tests.seed import seed_appointment, seed_data


def _service_with_appointment(db_session: Session):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    entities["user"].asaas_customer_id = "cus_local"
    db_session.commit()
    service = PaymentService(db_session)
    return service, appointment, entities


def _asaas_payment(payment_id: str) -> dict:
    return {
        "id": payment_id,
        "status": "PENDING",
        "invoiceUrl": f"https://asaas.test/{payment_id}",
    }


def test_charge_reuses_remote_match_after_uncertain_create(db_session: Session):
    service, appointment, _entities = _service_with_appointment(db_session)
    service.asaas.create_payment = AsyncMock(
        side_effect=AsaasUncertainResultError("timeout")
    )
    service.asaas.list_payments = AsyncMock(
        side_effect=[[], [_asaas_payment("pay_recovered")]]
    )

    payment = asyncio.run(service.create_charge(appointment.id, "pix"))

    assert payment.asaas_payment_id == "pay_recovered"
    assert service.asaas.create_payment.await_count == 1
    assert service.asaas.list_payments.await_count == 2


def test_charge_refuses_multiple_remote_matches(db_session: Session):
    service, appointment, _entities = _service_with_appointment(db_session)
    service.asaas.list_payments = AsyncMock(
        return_value=[_asaas_payment("pay_1"), _asaas_payment("pay_2")]
    )
    service.asaas.create_payment = AsyncMock()

    with pytest.raises(AsaasReconciliationError, match="multiple"):
        asyncio.run(service.create_charge(appointment.id, "pix"))

    service.asaas.create_payment.assert_not_awaited()


def test_customer_reuses_remote_external_reference(db_session: Session):
    entities = seed_data(db_session)
    service = PaymentService(db_session)
    service.asaas.list_customers = AsyncMock(return_value=[{"id": "cus_remote"}])
    service.asaas.create_customer = AsyncMock()

    customer_id = asyncio.run(service.ensure_asaas_customer(entities["user"].id))

    assert customer_id == "cus_remote"
    assert entities["user"].asaas_customer_id == "cus_remote"
    service.asaas.create_customer.assert_not_awaited()


def test_charge_uses_stable_external_reference(db_session: Session):
    service, appointment, _entities = _service_with_appointment(db_session)
    service.asaas.list_payments = AsyncMock(return_value=[])
    service.asaas.create_payment = AsyncMock(return_value=_asaas_payment("pay_new"))

    asyncio.run(service.create_charge(appointment.id, "pix"))

    assert service.asaas.create_payment.await_args.kwargs["external_reference"] == (
        f"appointment:{appointment.id}"
    )


def test_charge_uses_price_snapshot_instead_of_later_catalog_price(db_session: Session):
    service, appointment, entities = _service_with_appointment(db_session)
    appointment.service_price_cents = 7500
    entities["service"].price_cents = 9900
    db_session.commit()
    service.asaas.list_payments = AsyncMock(return_value=[])
    service.asaas.create_payment = AsyncMock(return_value=_asaas_payment("pay_snapshot"))

    payment = asyncio.run(service.create_charge(appointment.id, "pix"))

    assert payment.amount_cents == 7500
    assert service.asaas.create_payment.await_args.kwargs["value"] == 75.0
