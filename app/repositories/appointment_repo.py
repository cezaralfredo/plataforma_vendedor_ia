from datetime import datetime

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.repositories.base import BaseRepository


class AppointmentRepository(BaseRepository):
    ACTIVE_WHILE_UNEXPIRED = ("pending", "awaiting_payment")
    ALWAYS_BLOCKING = ("confirmed", "completed")

    def __init__(self, db: Session):
        super().__init__(db, Appointment)

    def list_by_user(self, user_id: int):
        return self.db.query(Appointment).filter(Appointment.user_id == user_id).order_by(Appointment.start_time.desc()).all()

    def list_by_professional(self, professional_id: int):
        return self.db.query(Appointment).filter(Appointment.professional_id == professional_id).order_by(Appointment.start_time.desc()).all()

    def find_conflicting(
        self,
        professional_id: int,
        start_time: datetime | str,
        end_time: datetime | str,
        exclude_id: int | None = None,
        now: datetime | None = None,
    ):
        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time)
        if isinstance(end_time, str):
            end_time = datetime.fromisoformat(end_time)

        now = now or datetime.now(start_time.tzinfo)
        active = or_(
            Appointment.status.in_(self.ALWAYS_BLOCKING),
            and_(
                Appointment.status.in_(self.ACTIVE_WHILE_UNEXPIRED),
                or_(Appointment.expires_at.is_(None), Appointment.expires_at > now),
            ),
        )
        query = self.db.query(Appointment).filter(
            Appointment.professional_id == professional_id,
            Appointment.start_time < end_time,
            Appointment.end_time > start_time,
            active,
        )
        if exclude_id:
            query = query.filter(Appointment.id != exclude_id)
        return query.all()

    def expire_reservations(self, now: datetime) -> int:
        return self.db.query(Appointment).filter(
            Appointment.status.in_(self.ACTIVE_WHILE_UNEXPIRED),
            Appointment.expires_at.is_not(None),
            Appointment.expires_at <= now,
        ).update({"status": "cancelled"}, synchronize_session=False)

    def expire_pending(self, now: datetime) -> int:
        return self.expire_reservations(now)

    def list_by_status(self, status: str):
        return self.db.query(Appointment).filter(Appointment.status == status).all()
