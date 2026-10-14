from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'cancelled', 'completed', 'awaiting_payment')",
            name="check_appointment_status",
        ),
        CheckConstraint("end_time > start_time", name="check_appointment_interval"),
        ExcludeConstraint(
            ("professional_id", "="),
            (text("tstzrange(start_time, end_time, '[)')"), "&&"),
            where=text(
                "status IN ('pending', 'awaiting_payment', 'confirmed', 'completed')"
            ),
            using="gist",
            name="exclude_professional_overlapping_appointments",
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    professional_id: Mapped[int] = mapped_column(
        ForeignKey("professionals.id"), nullable=False, index=True
    )
    service_id: Mapped[int] = mapped_column(
        ForeignKey("services.id"), nullable=False, index=True
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    notified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    service_price_cents: Mapped[int] = mapped_column(Integer, nullable=True)
    service_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=True)
    professional_commission_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user = relationship("User", back_populates="appointments")
    professional = relationship("Professional", back_populates="appointments")
    service = relationship("Service", back_populates="appointments")
    payments = relationship("Payment", back_populates="appointment")
    notifications = relationship("NotificationLog", back_populates="appointment")
