from datetime import date, datetime, timedelta, timezone

from app.main import (
    IST,
    compute_late_minutes,
    compute_overtime,
    compute_work_hours,
    ist_date,
    parse_calendar_date,
)


def test_ist_date_conversion():
    instant = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)
    assert ist_date(instant) == date(2026, 10, 13)


def test_late_minutes_within_grace_period():
    punch_in = datetime(2026, 10, 12, 4, 10, tzinfo=timezone.utc)
    assert compute_late_minutes(punch_in, "09:30") == 0


def test_late_minutes_after_grace_period():
    punch_in = datetime(2026, 10, 12, 4, 10, 1, tzinfo=timezone.utc)
    assert compute_late_minutes(punch_in, "09:30") == 10


def test_work_hours_rounding():
    punch_in = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
    punch_out = punch_in + timedelta(hours=8, minutes=20)
    assert compute_work_hours(punch_in, punch_out) == 8.33


def test_overtime_below_threshold():
    punch_out = datetime(2026, 10, 12, 18, 59, 59, tzinfo=IST)
    assert compute_overtime(punch_out, "18:30", "2026-10-12") == 0


def test_overtime_at_threshold():
    punch_out = datetime(2026, 10, 12, 19, 0, tzinfo=IST)
    assert compute_overtime(punch_out, "18:30", "2026-10-12") == 30


def test_parse_calendar_date_valid():
    assert parse_calendar_date("2026-10-12") == date(2026, 10, 12)
