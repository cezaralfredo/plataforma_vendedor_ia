import csv
import io
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.models.appointment import Appointment
from app.models.notification_delivery import NotificationDelivery
from app.models.notification_log import NotificationLog
from app.models.payment import Payment
from app.models.webhook_event import WebhookEvent
from tests.seed import seed_data


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": settings.admin_api_key}


def test_admin_appointments_hide_unpaid_cancelled_filter(
    client: TestClient, db_session: Session
):
    entities = seed_data(db_session)
    user = entities["user"]
    prof = entities["professional"]
    serv = entities["service"]

    # 1. Agendamento confirmado com pagamento confirmado
    apt_paid = Appointment(
        user_id=user.id,
        professional_id=prof.id,
        service_id=serv.id,
        start_time=datetime(2026, 8, 10, 10, 0, tzinfo=UTC),
        end_time=datetime(2026, 8, 10, 10, 45, tzinfo=UTC),
        status="confirmed",
    )
    db_session.add(apt_paid)
    db_session.flush()
    pay_paid = Payment(
        appointment_id=apt_paid.id,
        amount_cents=5000,
        status="confirmed",
    )
    db_session.add(pay_paid)

    # 2. Agendamento cancelado SEM pagamento (abandonado)
    apt_unpaid_cancelled = Appointment(
        user_id=user.id,
        professional_id=prof.id,
        service_id=serv.id,
        start_time=datetime(2026, 8, 11, 14, 0, tzinfo=UTC),
        end_time=datetime(2026, 8, 11, 14, 45, tzinfo=UTC),
        status="cancelled",
    )
    db_session.add(apt_unpaid_cancelled)

    # 3. Agendamento cancelado COM pagamento recebido/estornado
    apt_paid_cancelled = Appointment(
        user_id=user.id,
        professional_id=prof.id,
        service_id=serv.id,
        start_time=datetime(2026, 8, 12, 16, 0, tzinfo=UTC),
        end_time=datetime(2026, 8, 12, 16, 45, tzinfo=UTC),
        status="cancelled",
    )
    db_session.add(apt_paid_cancelled)
    db_session.flush()
    pay_cancelled_paid = Payment(
        appointment_id=apt_paid_cancelled.id,
        amount_cents=5000,
        status="received",
    )
    db_session.add(pay_cancelled_paid)
    db_session.commit()

    # Teste sem o filtro (todos aparecem)
    res_all = client.get("/admin/api/appointments", headers=_admin_headers())
    assert res_all.status_code == 200
    ids_all = [item["id"] for item in res_all.json()["data"]]
    assert apt_paid.id in ids_all
    assert apt_unpaid_cancelled.id in ids_all
    assert apt_paid_cancelled.id in ids_all

    # Teste com hide_unpaid_cancelled=true (o cancelado sem pagamento DEVE ser ocultado)
    res_filtered = client.get(
        "/admin/api/appointments?hide_unpaid_cancelled=true",
        headers=_admin_headers(),
    )
    assert res_filtered.status_code == 200
    ids_filtered = [item["id"] for item in res_filtered.json()["data"]]
    assert apt_paid.id in ids_filtered
    assert apt_paid_cancelled.id in ids_filtered
    assert apt_unpaid_cancelled.id not in ids_filtered


def test_maintenance_preview_and_csv_export(
    client: TestClient, db_session: Session
):
    entities = seed_data(db_session)
    user = entities["user"]
    prof = entities["professional"]
    serv = entities["service"]

    # Cria agendamento antigo (há 200 dias)
    past_date = datetime.now(UTC) - timedelta(days=200)
    apt_old = Appointment(
        user_id=user.id,
        professional_id=prof.id,
        service_id=serv.id,
        start_time=past_date,
        end_time=past_date + timedelta(minutes=45),
        status="completed",
        service_price_cents=7500,
    )
    db_session.add(apt_old)
    db_session.flush()

    pay_old = Payment(
        appointment_id=apt_old.id,
        amount_cents=7500,
        status="received",
        received_at=past_date,
    )
    db_session.add(pay_old)
    db_session.flush()

    deliv_old = NotificationDelivery(
        appointment_id=apt_old.id,
        payment_id=pay_old.id,
        event="payment.confirmed",
        status="sent",
    )
    db_session.add(deliv_old)

    log_old = NotificationLog(
        appointment_id=apt_old.id,
        type="confirmation",
        sent_at=past_date,
    )
    db_session.add(log_old)

    # Cria agendamento recente (há 10 dias) - NÃO deve ser incluído no corte de 6 meses
    recent_date = datetime.now(UTC) - timedelta(days=10)
    apt_recent = Appointment(
        user_id=user.id,
        professional_id=prof.id,
        service_id=serv.id,
        start_time=recent_date,
        end_time=recent_date + timedelta(minutes=45),
        status="confirmed",
    )
    db_session.add(apt_recent)
    db_session.commit()

    # 1. Testar página HTML
    res_page = client.get("/admin/maintenance", headers=_admin_headers())
    assert res_page.status_code == 200
    assert "Limpeza e Retenção" in res_page.text

    # 2. Testar API Preview com corte de 6 meses (180 dias)
    cutoff_str = (datetime.now(UTC) - timedelta(days=180)).date().isoformat()
    res_preview = client.get(
        f"/admin/api/maintenance/preview?cutoff_date={cutoff_str}",
        headers=_admin_headers(),
    )
    assert res_preview.status_code == 200
    preview = res_preview.json()
    assert preview["appointments_count"] == 1
    assert preview["completed_count"] == 1
    assert preview["payments_count"] == 1
    assert preview["notifications_count"] == 2
    assert preview["estimated_kb_freed"] > 0

    # 3. Testar Exportação CSV
    res_csv = client.get(
        f"/admin/api/maintenance/export-csv?cutoff_date={cutoff_str}",
        headers=_admin_headers(),
    )
    assert res_csv.status_code == 200
    assert res_csv.headers["content-type"].startswith("text/csv")
    csv_text = res_csv.text
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    assert len(rows) == 2  # Cabeçalho + 1 agendamento
    assert rows[0][0] == "ID Agendamento"
    assert str(apt_old.id) in rows[1]
    assert "75,00" in rows[1]


def test_maintenance_purge_execution(
    client: TestClient, db_session: Session
):
    entities = seed_data(db_session)
    user = entities["user"]
    prof = entities["professional"]
    serv = entities["service"]

    # Cria agendamento antigo abandonado (cancelado sem pagamento)
    past_date = datetime.now(UTC) - timedelta(days=220)
    apt_abandoned = Appointment(
        user_id=user.id,
        professional_id=prof.id,
        service_id=serv.id,
        start_time=past_date,
        end_time=past_date + timedelta(minutes=45),
        status="cancelled",
    )
    db_session.add(apt_abandoned)

    # Cria webhook antigo
    old_webhook = WebhookEvent(
        provider_event_id="evt_test_old_12345",
        received_at=past_date,
    )
    db_session.add(old_webhook)
    db_session.commit()

    cutoff_str = (datetime.now(UTC) - timedelta(days=180)).date().isoformat()

    # Requer confirmed: True
    res_unconfirmed = client.post(
        "/admin/api/maintenance/purge",
        json={"cutoff_date": cutoff_str, "confirmed": False},
        headers=_admin_headers(),
    )
    assert res_unconfirmed.status_code == 400

    target_id = apt_abandoned.id

    # Executa expurgo com sucesso
    res_purge = client.post(
        "/admin/api/maintenance/purge",
        json={
            "cutoff_date": cutoff_str,
            "unpaid_cancelled_only": True,
            "run_vacuum": True,
            "confirmed": True,
        },
        headers=_admin_headers(),
    )
    assert res_purge.status_code == 200
    data = res_purge.json()
    assert data["status"] == "success"
    assert data["deleted_appointments"] >= 1
    assert data["deleted_webhooks"] >= 1

    # Verifica se realmente sumiu do banco
    deleted_check = db_session.query(Appointment).filter(Appointment.id == target_id).first()
    assert deleted_check is None
