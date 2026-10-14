from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProfessionalCreate(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    bio: str | None = None
    photo_url: str | None = None
    active: bool = True


class ProfessionalUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    bio: str | None = None
    photo_url: str | None = None
    active: bool | None = None


class ProfessionalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str | None = None
    email: str | None = None
    bio: str | None = None
    photo_url: str | None = None
    active: bool
    created_at: datetime | None = None
