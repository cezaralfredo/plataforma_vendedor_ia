from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.services.asaas_client import (
    AsaasClient,
    AsaasIntegrationError,
    AsaasNotFoundError,
)
from tests.seed import seed_appointment, seed_data, seed_payment


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": settings.admin_api_key}


def _received_payment(db_session: Session):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    payment = seed_payment(db_session, appointment)
    payment.status = "received"
    appointment.status = "confirmed"
    db_session.commit()
    return appointment, payment


def test_admin_refund_calls_asaas_before_local_change(
    anonymous_client: TestClient,
    db_session: Session,
    monkeypatch,
):
    appointment, payment = _received_payment(db_session)
    refund = AsyncMock(
        return_value={"id": payment.asaas_payment_id, "status": "REFUNDED"}
    )
    monkeypatch.setattr(AsaasClient, "refund_payment", refund)

    response = anonymous_client.post(
        f"/admin/payments/{payment.id}/action",
        json={"action": "refund"},
        headers=_admin_headers(),
    )

    assert response.status_code == 200
    assert refund.await_count == 1
    db_session.refresh(payment)
    db_session.refresh(appointment)
    assert payment.status == "refunded"
    assert appointment.status == "cancelled"


def test_failed_asaas_refund_keeps_local_status(
    anonymous_client: TestClient,
    db_session: Session,
    monkeypatch,
):
    appointment, payment = _received_payment(db_session)
    monkeypatch.setattr(
        AsaasClient,
        "refund_payment",
        AsyncMock(side_effect=AsaasIntegrationError("rejected")),
    )

    response = anonymous_client.post(
        f"/admin/payments/{payment.id}/action",
        json={"action": "refund"},
        headers=_admin_headers(),
    )

    assert response.status_code == 502
    db_session.refresh(payment)
    db_session.refresh(appointment)
    assert payment.status == "received"
    assert appointment.status == "confirmed"


def test_admin_refresh_reads_real_provider_status(
    anonymous_client: TestClient,
    db_session: Session,
    monkeypatch,
):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    payment = seed_payment(db_session, appointment)
    get_payment = AsyncMock(
        return_value={"id": payment.asaas_payment_id, "status": "CONFIRMED"}
    )
    monkeypatch.setattr(AsaasClient, "get_payment", get_payment)

    response = anonymous_client.post(
        f"/admin/payments/{payment.id}/action",
        json={"action": "refresh"},
        headers=_admin_headers(),
    )

    assert response.status_code == 200
    assert get_payment.await_count == 1
    payload = response.json()
    assert payload["message"] == "Pagamento sincronizado: confirmado."
    assert payload["changed"] is True
    assert payload["payment"]["id"] == payment.id
    assert payload["payment"]["status"] == "confirmed"
    db_session.refresh(payment)
    assert payment.status == "confirmed"


def test_admin_refresh_reports_when_provider_status_did_not_change(
    anonymous_client: TestClient,
    db_session: Session,
    monkeypatch,
):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    payment = seed_payment(db_session, appointment)
    monkeypatch.setattr(
        AsaasClient,
        "get_payment",
        AsyncMock(return_value={"id": payment.asaas_payment_id, "status": "PENDING"}),
    )

    response = anonymous_client.post(
        f"/admin/payments/{payment.id}/action",
        json={"action": "refresh"},
        headers=_admin_headers(),
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Pagamento já estava atualizado: pendente."
    assert response.json()["changed"] is False


def test_admin_payment_action_rejects_unknown_action(
    anonymous_client: TestClient,
    db_session: Session,
):
    _appointment, payment = _received_payment(db_session)

    response = anonymous_client.post(
        f"/admin/payments/{payment.id}/action",
        json={"action": "mark_paid_locally"},
        headers=_admin_headers(),
    )

    assert response.status_code == 422


def test_admin_refresh_cancels_when_provider_returns_deleted_true(
    anonymous_client: TestClient,
    db_session: Session,
    monkeypatch,
):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    payment = seed_payment(db_session, appointment)
    payment.status = "pending"
    appointment.status = "pending"
    db_session.commit()

    get_payment = AsyncMock(
        return_value={"id": payment.asaas_payment_id, "deleted": True, "status": "PENDING"}
    )
    monkeypatch.setattr(AsaasClient, "get_payment", get_payment)

    response = anonymous_client.post(
        f"/admin/payments/{payment.id}/action",
        json={"action": "refresh"},
        headers=_admin_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Pagamento sincronizado: cancelado."
    assert payload["changed"] is True
    assert payload["payment"]["status"] == "cancelled"
    db_session.refresh(payment)
    db_session.refresh(appointment)
    assert payment.status == "cancelled"
    assert appointment.status == "cancelled"


def test_admin_refresh_cancels_when_provider_returns_404_not_found(
    anonymous_client: TestClient,
    db_session: Session,
    monkeypatch,
):
    entities = seed_data(db_session)
    user = entities["user"]
    user.asaas_customer_id = "cus_deleted_123"
    appointment = seed_appointment(db_session, entities)
    payment = seed_payment(db_session, appointment)
    payment.status = "pending"
    appointment.status = "pending"
    db_session.commit()

    get_payment = AsyncMock(side_effect=AsaasNotFoundError("Asaas returned HTTP 404"))
    get_customer = AsyncMock(side_effect=AsaasNotFoundError("Asaas returned HTTP 404"))
    monkeypatch.setattr(AsaasClient, "get_payment", get_payment)
    monkeypatch.setattr(AsaasClient, "get_customer", get_customer)

    response = anonymous_client.post(
        f"/admin/payments/{payment.id}/action",
        json={"action": "refresh"},
        headers=_admin_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Pagamento sincronizado: cancelado."
    assert payload["changed"] is True
    assert payload["payment"]["status"] == "cancelled"
    db_session.refresh(payment)
    db_session.refresh(appointment)
    db_session.refresh(user)
    assert payment.status == "cancelled"
    assert appointment.status == "cancelled"
    assert user.asaas_customer_id is None


def test_admin_payments_api_summary_and_filters(
    anonymous_client: TestClient,
    db_session: Session,
):
    entities = seed_data(db_session)
    appointment1 = seed_appointment(db_session, entities)
    payment1 = seed_payment(db_session, appointment1)
    payment1.status = "received"
    payment1.amount_cents = 5000

    from datetime import UTC, datetime, timedelta

    from app.models.appointment import Appointment
    from app.models.payment import Payment

    appointment2 = Appointment(
        user_id=entities["user"].id,
        professional_id=entities["professional"].id,
        service_id=entities["service"].id,
        start_time=datetime.now(UTC) + timedelta(days=2),
        end_time=datetime.now(UTC) + timedelta(days=2, hours=1),
        status="pending",
    )
    db_session.add(appointment2)
    db_session.flush()

    payment2 = Payment(
        appointment_id=appointment2.id,
        amount_cents=3500,
        billing_type="pix",
        status="pending",
        asaas_payment_id="pay_test_pending_456",
    )
    db_session.add(payment2)
    db_session.commit()

    # 1. Total & Summary test
    response = anonymous_client.get("/admin/api/payments", headers=_admin_headers())
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 2
    summary = data["summary"]
    assert summary["received_cents"] >= 5000
    assert summary["received_count"] >= 1
    assert summary["pending_cents"] >= 3500
    assert summary["pending_count"] >= 1

    # 2. Filter by status 'received'
    r_recv = anonymous_client.get(
        "/admin/api/payments?status=received", headers=_admin_headers()
    )
    assert r_recv.status_code == 200
    recv_data = r_recv.json()
    assert all(p["status"] == "received" for p in recv_data["data"])
    assert any(p["id"] == payment1.id for p in recv_data["data"])
    assert not any(p["id"] == payment2.id for p in recv_data["data"])

    # 3. Filter by status 'pending'
    r_pend = anonymous_client.get(
        "/admin/api/payments?status=pending", headers=_admin_headers()
    )
    assert r_pend.status_code == 200
    pend_data = r_pend.json()
    assert all(p["status"] == "pending" for p in pend_data["data"])
    assert any(p["id"] == payment2.id for p in pend_data["data"])
    assert not any(p["id"] == payment1.id for p in pend_data["data"])

    # 4. Filter by status alias 'paid'
    r_paid = anonymous_client.get(
        "/admin/api/payments?status=paid", headers=_admin_headers()
    )
    assert r_paid.status_code == 200
    assert any(p["id"] == payment1.id for p in r_paid.json()["data"])
    assert not any(p["id"] == payment2.id for p in r_paid.json()["data"])

    # 5. Search by Payment ID with '#'
    r_search_id = anonymous_client.get(
        f"/admin/api/payments?search=%23{payment1.id}", headers=_admin_headers()
    )
    assert r_search_id.status_code == 200
    assert any(p["id"] == payment1.id for p in r_search_id.json()["data"])

    # 6. Search by Service Name
    r_search_svc = anonymous_client.get(
        f"/admin/api/payments?search={entities['service'].name}",
        headers=_admin_headers(),
    )
    assert r_search_svc.status_code == 200
    assert len(r_search_svc.json()["data"]) >= 2

    # 7. Search by Client Name
    r_search_cli = anonymous_client.get(
        f"/admin/api/payments?search={entities['user'].name[:4]}",
        headers=_admin_headers(),
    )
    assert r_search_cli.status_code == 200
    assert len(r_search_cli.json()["data"]) >= 2


def test_admin_kpis_includes_revenue_and_pending_totals(
    anonymous_client: TestClient,
    db_session: Session,
):
    _appointment, _payment = _received_payment(db_session)
    response = anonymous_client.get("/admin/api/kpis", headers=_admin_headers())
    assert response.status_code == 200
    kpis = response.json()
    assert "revenue_total_cents" in kpis
    assert "pending_total_cents" in kpis
    assert kpis["revenue_total_cents"] >= 0


def test_admin_payments_html_page_renders_new_dashboard_and_filters(
    anonymous_client: TestClient,
    db_session: Session,
):
    _appointment, _payment = _received_payment(db_session)
    response = anonymous_client.get("/admin/payments", headers=_admin_headers())
    assert response.status_code == 200
    html = response.text
    assert "Valor Recebido" in html
    assert "Valores Pendentes" in html
    assert "Valor Total (Filtro)" in html
    assert "Filtrar Data Por" in html
    assert "applyFilters()" in html
    assert "resetFilters()" in html

