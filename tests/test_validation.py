import pytest
from pydantic import ValidationError

from app.main import EmployeeIn, PunchInIn, PunchOutIn


@pytest.mark.parametrize("value", [True, 1234567890, 123.45, "1791792000000"])
def test_punch_in_rejects_invalid_timestamps(value):
    with pytest.raises(ValidationError):
        PunchInIn(emp_code="TEST001", punched_at=value)


@pytest.mark.parametrize("status", ["ABSENT", "LEAVE", "INVALID", "present"])
def test_punch_in_rejects_invalid_status(status):
    with pytest.raises(ValidationError):
        PunchInIn(emp_code="TEST001", status=status)


@pytest.mark.parametrize("status", ["PRESENT", "WFH", "ON_DUTY"])
def test_punch_in_accepts_supported_status(status):
    request = PunchInIn(emp_code="TEST001", status=status)
    assert request.status == status


def test_punch_in_accepts_missing_timestamp():
    request = PunchInIn(emp_code="TEST001")
    assert request.punched_at is None


def test_employee_model_accepts_required_fields():
    employee = EmployeeIn(
        emp_code="TEST001",
        name="Test Employee",
        email="test@example.com",
        department="Engineering",
        joined_on="2026-10-01",
    )
    assert employee.emp_code == "TEST001"


def test_punch_out_model_accepts_missing_timestamp():
    request = PunchOutIn(emp_code="TEST001")
    assert request.punched_at is None
