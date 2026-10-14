from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class NotificationLog(Base):
    __tablename__ = "notification_log"
    __table_args__ = (
        CheckConstraint(
            "type IN ('confirmation', 'reminder', 'cancellation', 'payment_received', 'payment_overdue')",
            name="check_notification_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    appointment = relationship("Appointment", back_populates="notifications")
