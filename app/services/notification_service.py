import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models.appointment import Appointment
from app.models.notification_delivery import NotificationDelivery
from app.models.notification_log import NotificationLog
from app.models.payment import Payment

logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    """Normaliza valores do SQLite sem fuso para comparação segura em testes."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def format_payment_confirmation_message(appointment: Appointment | None, payment: Payment) -> str:
    """Gera mensagem formatada e humanizada de confirmação para envio via WhatsApp."""
    user = (appointment.user if appointment and getattr(appointment, "user", None) else getattr(payment, "user", None))
    user_name = user.name if user else "Cliente"
    amount = f"R$ {payment.amount_cents / 100:.2f}"
    billing = (payment.billing_type or "PIX").upper()

    if getattr(payment, "product", None):
        product_name = payment.product.name
        return (
            f"Olá, {user_name}! 👋\n\n"
            f"✅ Seu pagamento de {amount} ({billing}) foi confirmado com sucesso!\n\n"
            f"📦 *Detalhes da sua Compra:*\n"
            f"• *Produto:* {product_name}\n"
            f"• *Código do Pedido:* #{payment.id}\n\n"
            f"Seu pedido foi confirmado e logo será despachado. Qualquer dúvida, é só responder por aqui!"
        )

    apt_id_str = f"#{appointment.id}" if appointment else f"#{payment.id}"
    return (
        f"Olá, {user_name}! 👋\n\n"
        f"✅ Seu pagamento de {amount} ({billing}) foi confirmado com sucesso!\n\n"
        f"📋 *Detalhes da sua Compra:*\n"
        f"• *Código:* {apt_id_str}\n\n"
        f"Seu pagamento foi confirmado com sucesso. Qualquer dúvida, é só responder por aqui!"
    )


def build_payment_notification_payload(appointment: Appointment | None, payment: Payment) -> dict[str, Any]:
    """Monta payload padronizado para envio ao n8n ou webhook."""
    user = (appointment.user if appointment and getattr(appointment, "user", None) else getattr(payment, "user", None))
    product = getattr(payment, "product", None)

    client_phone = user.phone if user else ""
    whatsapp = getattr(user, "whatsapp_number", None) or client_phone

    return {
        "event": "payment.confirmed",
        "timestamp": datetime.now(UTC).isoformat(),
        "appointment_id": appointment.id if appointment else None,
        "chatId": whatsapp,
        "whatsapp": whatsapp,
        "payment_id": payment.id,
        "asaas_payment_id": payment.asaas_payment_id,
        "status": appointment.status if appointment else "confirmed",
        "payment_status": payment.status,
        "amount_cents": payment.amount_cents,
        "billing_type": payment.billing_type,
        "client": {
            "id": user.id if user else None,
            "name": user.name if user else "Cliente",
            "phone": client_phone,
            "whatsapp_number": whatsapp,
        },
        "product": {
            "id": product.id if product else None,
            "name": product.name if product else None,
            "price_cents": product.price_cents if product else None,
            "weight_kg": float(product.weight_kg) if product and product.weight_kg is not None else None,
        } if product else None,
        "appointment": {
            "id": appointment.id,
            "start_time": appointment.start_time.isoformat() if appointment.start_time else None,
            "end_time": appointment.end_time.isoformat() if appointment.end_time else None,
            "notes": appointment.notes,
        } if appointment else None,
        "formatted_message": format_payment_confirmation_message(appointment, payment),
    }


class NotificationService:
    def __init__(self, db: Session):
        self.db = db

    def get_effective_webhook_url(self) -> str:
        """O n8n é o único orquestrador de entregas assíncronas da Agenda.

        O Hermes mantém a inteligência e o transporte nativo do WhatsApp, mas
        não expõe um webhook de entrega compatível com a API da Agenda.
        """
        return getattr(settings, "n8n_webhook_url", "")

    def queue_payment_confirmed(self, appointment_id: int, payment_id: int) -> NotificationDelivery:
        """Registra a confirmação em uma outbox idempotente na mesma transação do pagamento."""
        delivery = (
            self.db.query(NotificationDelivery)
            .filter(
                NotificationDelivery.payment_id == payment_id,
                NotificationDelivery.event == "payment.confirmed",
            )
            .first()
        )
        if delivery:
            return delivery

        delivery = NotificationDelivery(
            appointment_id=appointment_id,
            payment_id=payment_id,
            event="payment.confirmed",
            status="pending",
        )
        self.db.add(delivery)
        self.db.flush()
        return delivery

    def recover_unnotified_payment_confirmations(self, limit: int = 100) -> int:
        """Recupera confirmações já registradas antes de uma indisponibilidade do n8n."""
        appointments = (
            self.db.query(Appointment)
            .join(Payment, Payment.appointment_id == Appointment.id)
            .filter(
                Appointment.status == "confirmed",
                Appointment.notified_at.is_(None),
                Payment.status.in_(("received", "confirmed")),
            )
            .order_by(Payment.received_at, Payment.id)
            .limit(limit)
            .all()
        )
        created = 0
        for appointment in appointments:
            payment = (
                self.db.query(Payment)
                .filter(
                    Payment.appointment_id == appointment.id,
                    Payment.status.in_(("received", "confirmed")),
                )
                .order_by(Payment.received_at.desc(), Payment.id.desc())
                .first()
            )
            if not payment:
                continue
            existing = (
                self.db.query(NotificationDelivery)
                .filter(
                    NotificationDelivery.payment_id == payment.id,
                    NotificationDelivery.event == "payment.confirmed",
                )
                .first()
            )
            if existing:
                continue
            self.queue_payment_confirmed(appointment.id, payment.id)
            created += 1
        if created:
            self.db.commit()
        return created

    def get_delivery_payload(self, delivery: NotificationDelivery) -> dict[str, Any] | None:
        appointment = (
            self.db.query(Appointment)
            .options(
                joinedload(Appointment.user),
            )
            .filter(Appointment.id == delivery.appointment_id)
            .first()
        )
        if not appointment:
            logger.warning("Appointment %s not found for notification delivery", delivery.appointment_id)
            return None

        payment = self.db.query(Payment).filter(Payment.id == delivery.payment_id).first()
        if not payment:
            logger.warning("Payment %s not found for notification delivery", delivery.payment_id)
            return None

        payload = build_payment_notification_payload(appointment, payment)
        payload["delivery_id"] = delivery.id
        payload["attempt"] = delivery.attempts
        return payload

    async def dispatch_payment_confirmed(self, delivery_id: int) -> bool:
        """Acorda o n8n, sem confundir aceitação do webhook com entrega da mensagem."""
        delivery = self.db.get(NotificationDelivery, delivery_id)
        if not delivery or delivery.status == "sent":
            return False

        webhook_url = self.get_effective_webhook_url()
        if not webhook_url:
            logger.info(
                "No notification webhook configured. Delivery %s remains pending for retry.",
                delivery.id,
            )
            return False

        # Somente o identificador interno é enviado ao gatilho. O n8n busca os
        # dados completos autenticado, evitando expor dados do cliente em logs.
        payload = {"delivery_id": delivery.id, "event": delivery.event}
        headers = {"Content-Type": "application/json"}
        token = getattr(settings, "notification_webhook_token", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(webhook_url, json=payload, headers=headers)
                response.raise_for_status()

            logger.info(
                "Payment confirmation delivery %s accepted by %s",
                delivery.id,
                webhook_url,
            )
            return True
        except Exception as e:
            logger.warning(
                "Failed to wake notification workflow %s for delivery %s: %s",
                webhook_url,
                delivery.id,
                e,
            )
            return False

    def claim_delivery(self, delivery_id: int) -> NotificationDelivery | None:
        """Reserva uma entrega para um único worker e recupera leases abandonados."""
        delivery = (
            self.db.query(NotificationDelivery)
            .filter(NotificationDelivery.id == delivery_id)
            .with_for_update()
            .first()
        )
        if not delivery or delivery.status in {"sent", "failed"}:
            return None

        now = datetime.now(UTC)
        lease_expired = (
            delivery.status == "processing"
            and delivery.claimed_at is not None
            and _as_utc(delivery.claimed_at)
            <= now - timedelta(seconds=settings.notification_delivery_lease_seconds)
        )
        if delivery.status == "processing" and not lease_expired:
            return None
        if delivery.status == "pending" and _as_utc(delivery.next_attempt_at) > now:
            return None
        if delivery.attempts >= settings.notification_delivery_max_attempts:
            delivery.status = "failed"
            delivery.last_error = "Número máximo de tentativas atingido sem confirmação do provedor."
            self.db.commit()
            return None

        delivery.status = "processing"
        delivery.attempts += 1
        delivery.claimed_at = now
        delivery.last_error = None
        self.db.commit()
        return delivery

    def mark_delivery_sent(
        self, delivery_id: int, provider_message_id: str | None = None
    ) -> NotificationDelivery | None:
        delivery = self.db.get(NotificationDelivery, delivery_id)
        if not delivery:
            return None
        if delivery.status == "sent":
            return delivery
        if delivery.status != "processing":
            return None

        now = datetime.now(UTC)
        delivery.status = "sent"
        delivery.sent_at = now
        delivery.provider_message_id = provider_message_id
        delivery.last_error = None
        appointment = self.db.get(Appointment, delivery.appointment_id)
        if appointment:
            appointment.notified_at = now
            already_logged = (
                self.db.query(NotificationLog)
                .filter(
                    NotificationLog.appointment_id == appointment.id,
                    NotificationLog.type == "confirmation",
                )
                .first()
            )
            if not already_logged:
                self.db.add(
                    NotificationLog(
                        appointment_id=appointment.id,
                        type="confirmation",
                        sent_at=now,
                    )
                )
        self.db.commit()
        return delivery

    def defer_delivery(self, delivery_id: int, error: str) -> NotificationDelivery | None:
        delivery = self.db.get(NotificationDelivery, delivery_id)
        if not delivery or delivery.status == "sent":
            return None
        now = datetime.now(UTC)
        delivery.last_error = error[:1000]
        delivery.claimed_at = None
        if delivery.attempts >= settings.notification_delivery_max_attempts:
            delivery.status = "failed"
        else:
            delay_seconds = min(60 * (2 ** max(delivery.attempts - 1, 0)), 3600)
            delivery.status = "pending"
            delivery.next_attempt_at = now + timedelta(seconds=delay_seconds)
        self.db.commit()
        return delivery
