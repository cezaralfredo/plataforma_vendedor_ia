from datetime import UTC, datetime

from app.business_time import as_business_time


def test_naive_datetime_is_interpreted_in_business_timezone():
    value = as_business_time(datetime(2026, 8, 24, 9, 0))
    assert value.isoformat() == "2026-08-24T09:00:00-03:00"


def test_utc_datetime_is_converted_to_business_timezone():
    value = as_business_time(datetime(2026, 8, 24, 12, 0, tzinfo=UTC))
    assert value.isoformat() == "2026-08-24T09:00:00-03:00"


