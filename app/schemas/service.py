from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ServiceCreate(BaseModel):
    name: str
    description: str | None = None
    duration_minutes: int = Field(gt=0)
    price_cents: int = Field(ge=0)
    category: str | None = None
    active: bool = True


class ServiceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    duration_minutes: int | None = Field(default=None, gt=0)
    price_cents: int | None = Field(default=None, ge=0)
    category: str | None = None
    active: bool | None = None


class ServiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    duration_minutes: int
    price_cents: int
    category: str | None = None
    active: bool
    created_at: datetime | None = None


class ServiceOfferingRead(BaseModel):
    service_id: int
    professional_id: int
    name: str
    description: str | None = None
    category: str | None = None
    price_cents: int
    duration_minutes: int
    commission_percent: Decimal
