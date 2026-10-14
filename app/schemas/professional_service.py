from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProfessionalServiceCreate(BaseModel):
    service_id: int
    commission_percent: Decimal = Field(
        default=Decimal("10.00"), ge=Decimal("0"), le=Decimal("100")
    )
    active: bool = True


class ProfessionalServiceUpdate(BaseModel):
    commission_percent: Decimal | None = Field(
        default=None, ge=Decimal("0"), le=Decimal("100")
    )
    active: bool | None = None


class ProfessionalServiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    professional_id: int
    service_id: int
    commission_percent: Decimal
    active: bool
