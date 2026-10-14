from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.business_time import as_business_time


class AppointmentCreate(BaseModel):
    user_id: int
    professional_id: int
    service_id: int
    start_time: datetime
    end_time: datetime
    notes: str | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def normalize_datetime(cls, value: datetime) -> datetime:
        return as_business_time(value)

    @model_validator(mode="after")
    def validate_interval(self):
        if self.end_time <= self.start_time:
            raise ValueError("O hor\u00e1rio final deve ser posterior ao inicial")
        return self


class AppointmentUpdate(BaseModel):
    status: str | None = None
    notes: str | None = None
    notified_at: datetime | None = None
    expires_at: datetime | None = None


class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    professional_id: int
    service_id: int
    start_time: datetime
    end_time: datetime
    status: str
    expires_at: datetime | None = None
    notified_at: datetime | None = None
    notes: str | None = None
    created_at: datetime | None = None

    @field_validator(
        "start_time",
        "end_time",
        "expires_at",
        "notified_at",
        "created_at",
        mode="before",
    )
    @classmethod
    def normalize_response_datetime(cls, value: datetime | None):
        return as_business_time(value) if value is not None else None
