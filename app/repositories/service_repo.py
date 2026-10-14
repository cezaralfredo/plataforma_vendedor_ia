from sqlalchemy.orm import Session

from app.models.service import Service
from app.repositories.base import BaseRepository


class ServiceRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, Service)

    def list_by_professional(self, professional_id: int):
        return (
            self.db.query(Service)
            .join(Service.professional_offerings)
            .filter(
                Service.active.is_(True),
                Service.professional_offerings.any(
                    professional_id=professional_id,
                    active=True,
                ),
            )
            .all()
        )

    def list_by_category(
        self, category: str, skip: int = 0, limit: int = 100, active_only: bool = False
    ):
        query = self.db.query(Service).filter(Service.category == category)
        if active_only:
            query = query.filter(Service.active.is_(True))
        return query.order_by(Service.name).offset(skip).limit(limit).all()

    def list_catalog(self, skip: int = 0, limit: int = 100, active_only: bool = False):
        query = self.db.query(Service)
        if active_only:
            query = query.filter(Service.active.is_(True))
        return query.order_by(Service.name).offset(skip).limit(limit).all()
