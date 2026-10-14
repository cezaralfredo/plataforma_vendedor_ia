from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base


class RelatedRecordsError(ValueError):
    pass


class BaseRepository:
    def __init__(self, db: Session, model: type[Base]):
        self.db = db
        self.model = model

    def create(self, **kwargs):
        obj = self.model(**kwargs)
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def get(self, id: int):
        return self.db.query(self.model).filter_by(id=id).first()

    def list(self, skip: int = 0, limit: int = 100):
        return self.db.query(self.model).offset(skip).limit(limit).all()

    def update(self, id: int, **kwargs):
        obj = self.get(id)
        if not obj:
            return None
        for key, value in kwargs.items():
            setattr(obj, key, value)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete(self, id: int):
        obj = self.get(id)
        if not obj:
            return False
        self.db.delete(obj)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise RelatedRecordsError("O registro possui histórico relacionado") from exc
        return True
