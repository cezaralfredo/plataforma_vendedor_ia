from datetime import date, datetime, time

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Availability(Base):
    __tablename__ = "availability"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="check_day_of_week"),
        CheckConstraint(
            "(day_of_week IS NOT NULL AND specific_date IS NULL) OR (day_of_week IS NULL AND specific_date IS NOT NULL)",
            name="check_availability_type",
        ),
        CheckConstraint(
            "start_time IS NOT NULL AND end_time IS NOT NULL AND end_time > start_time",
            name="check_availability_interval",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    professional_id: Mapped[int] = mapped_column(
        ForeignKey("professionals.id"), nullable=False, index=True
    )
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=True)
    end_time: Mapped[time] = mapped_column(Time, nullable=True)
    specific_date: Mapped[date] = mapped_column(Date, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    professional = relationship("Professional", back_populates="availability")
