from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.business_time import as_business_time


class AvailabilityCreate(BaseModel):
    professional_id: int
    day_of_week: int | None = None
    start_time: time | None = None
    end_time: time | None = None
    specific_date: date | None = None

    @model_validator(mode="after")
    def validate_schedule(self):
        if (self.day_of_week is None) == (self.specific_date is None):
            raise ValueError("Informe um dia da semana ou uma data espec\u00edfica")
        if self.start_time is None or self.end_time is None:
            raise ValueError("Os hor\u00e1rios de in\u00edcio e fim s\u00e3o obrigat\u00f3rios")
        if self.end_time <= self.start_time:
            raise ValueError("O hor\u00e1rio final deve ser posterior ao inicial")
        return self


class AvailabilityUpdate(BaseModel):
    day_of_week: int | None = None
    start_time: time | None = None
    end_time: time | None = None
    specific_date: date | None = None


class AvailabilityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    professional_id: int
    day_of_week: int | None = None
    start_time: time | None = None
    end_time: time | None = None
    specific_date: date | None = None
    created_at: datetime | None = None


class TimeSlot(BaseModel):
    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def normalize_datetime(cls, value: datetime) -> datetime:
        return as_business_time(value)
