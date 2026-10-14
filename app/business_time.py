from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from app.config import settings


def business_tz() -> ZoneInfo:
    return ZoneInfo(settings.app_timezone)


def as_business_time(value: datetime) -> datetime:
    timezone = business_tz()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone)
    return value.astimezone(timezone)


def business_datetime(day: date, value: time) -> datetime:
    return datetime.combine(day, value, tzinfo=business_tz())


def utc_now() -> datetime:
    return datetime.now(UTC)
