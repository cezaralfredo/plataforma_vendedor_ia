from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.notification_delivery import NotificationDelivery
from app.security import require_api_key
from app.services.notification_service import NotificationService

router = APIRouter(
    prefix="/internal/notification-deliveries",
    tags=["internal-notifications"],
    dependencies=[Depends(require_api_key)],
)


class DeliveryAck(BaseModel):
    provider_message_id: str | None = Field(default=None, max_length=160)


class DeliveryFailure(BaseModel):
    error: str = Field(min_length=1, max_length=1000)


def _serialize(delivery: NotificationDelivery) -> dict:
    return {
        "id": delivery.id,
        "appointment_id": delivery.appointment_id,
        "payment_id": delivery.payment_id,
        "event": delivery.event,
        "status": delivery.status,
        "attempts": delivery.attempts,
        "next_attempt_at": delivery.next_attempt_at,
        "claimed_at": delivery.claimed_at,
        "sent_at": delivery.sent_at,
        "provider_message_id": delivery.provider_message_id,
        "last_error": delivery.last_error,
    }


@router.get("")
def list_due_deliveries(
    limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)
):
    """Lista IDs pendentes. A posse da mensagem só ocorre no endpoint claim."""
    service = NotificationService(db)
    recovered = service.recover_unnotified_payment_confirmations(limit=limit)
    now = datetime.now(UTC)
    lease_cutoff = now - timedelta(seconds=settings.notification_delivery_lease_seconds)
    deliveries = (
        db.query(NotificationDelivery)
        .filter(
            or_(
                (NotificationDelivery.status == "pending")
                & (NotificationDelivery.next_attempt_at <= now),
                (NotificationDelivery.status == "processing")
                & (NotificationDelivery.claimed_at <= lease_cutoff),
            )
        )
        .order_by(NotificationDelivery.next_attempt_at, NotificationDelivery.id)
        .limit(limit)
        .all()
    )
    return {
        "recovered": recovered,
        "deliveries": [_serialize(delivery) for delivery in deliveries],
    }


@router.post("/{delivery_id}/claim")
def claim_delivery(delivery_id: int, db: Session = Depends(get_db)):
    service = NotificationService(db)
    delivery = service.claim_delivery(delivery_id)
    if not delivery:
        raise HTTPException(status_code=409, detail="Entrega indisponível para processamento")
    payload = service.get_delivery_payload(delivery)
    if payload is None:
        service.defer_delivery(delivery.id, "Dados da confirmação não encontrados")
        raise HTTPException(status_code=409, detail="Dados da entrega não encontrados")
    return {"delivery": _serialize(delivery), "payload": payload}


@router.post("/{delivery_id}/sent")
def acknowledge_delivery(
    delivery_id: int, data: DeliveryAck, db: Session = Depends(get_db)
):
    delivery = NotificationService(db).mark_delivery_sent(
        delivery_id, data.provider_message_id
    )
    if not delivery:
        raise HTTPException(status_code=409, detail="Entrega não está em processamento")
    return {"delivery": _serialize(delivery)}


@router.post("/{delivery_id}/failed")
def defer_delivery(
    delivery_id: int, data: DeliveryFailure, db: Session = Depends(get_db)
):
    delivery = NotificationService(db).defer_delivery(delivery_id, data.error)
    if not delivery:
        raise HTTPException(status_code=404, detail="Entrega não encontrada")
    return {"delivery": _serialize(delivery)}
