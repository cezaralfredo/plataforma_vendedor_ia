from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.repositories.base import BaseRepository


class PaymentRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, Payment)

    def list_by_appointment(self, appointment_id: int):
        return self.db.query(Payment).filter(Payment.appointment_id == appointment_id).all()

    def find_by_asaas_id(self, asaas_payment_id: str):
        return self.db.query(Payment).filter(Payment.asaas_payment_id == asaas_payment_id).first()

    def list_pending_with_asaas(self):
        return self.db.query(Payment).filter(
            Payment.status.in_(["pending", "awaiting_payment"]),
            Payment.asaas_payment_id.isnot(None)
        ).all()