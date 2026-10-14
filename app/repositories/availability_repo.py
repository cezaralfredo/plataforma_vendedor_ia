from datetime import date

from sqlalchemy.orm import Session

from app.models.availability import Availability
from app.repositories.base import BaseRepository


class AvailabilityRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, Availability)

    def list_by_professional(self, professional_id: int):
        return self.db.query(Availability).filter(
            Availability.professional_id == professional_id
        ).all()

    def find_by_day(self, professional_id: int, day_of_week: int):
        return self.db.query(Availability).filter(
            Availability.professional_id == professional_id,
            Availability.day_of_week == day_of_week,
        ).all()

    def find_by_date(self, professional_id: int, specific_date: date):
        return self.db.query(Availability).filter(
            Availability.professional_id == professional_id,
            Availability.specific_date == specific_date,
        ).all()
