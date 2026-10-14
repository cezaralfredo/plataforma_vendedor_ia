from sqlalchemy.orm import Session

from app.models.professional import Professional
from app.repositories.base import BaseRepository


class ProfessionalRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, Professional)

    def list_active(self):
        return self.db.query(Professional).filter(Professional.active.is_(True)).all()
