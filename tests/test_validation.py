from datetime import date

from leave.db import get_employee
from leave.holidays import upsert_holiday
from leave.requests import create_request
from leave.seed import upsert_employee
from leave.validation import validate_request

TODAY = date(2026, 6, 8)  # a Monday; 2026-06-13 is the following Saturday


def _alice(db):
    upsert_employee(db, "U_ALICE", "Alice", None, {"sick": 30, "vacation": 2, "personal": 5})
    return get_employee(db, "U_ALICE")


def test_valid_request_has_no_errors(db):
    alice = _alice(db)
    errors = validate_request(db, alice, "vacation", date(2026, 6, 10), date(2026, 6, 11), TODAY)
    assert errors == {}


def test_end_before_start(db):
    alice = _alice(db)
    errors = validate_request(db, alice, "vacation", date(2026, 6, 12), date(2026, 6, 10), TODAY)
    assert "end_date" in errors


def test_start_in_past(db):
    alice = _alice(db)
    errors = validate_request(db, alice, "vacation", date(2026, 6, 1), date(2026, 6, 2), TODAY)
    assert "start_date" in errors


def test_exceeds_balance(db):
    alice = _alice(db)  # vacation allowance = 2
    # Wed-Fri = 3 weekdays > 2
    errors = validate_request(db, alice, "vacation", date(2026, 6, 10), date(2026, 6, 12), TODAY)
    assert "leave_type" in errors


def test_overlap(db):
    alice = _alice(db)
    create_request(db, "U_ALICE", "sick", date(2026, 6, 10), date(2026, 6, 11), None)
    errors = validate_request(db, alice, "sick", date(2026, 6, 11), date(2026, 6, 12), TODAY)
    assert "end_date" in errors


def test_weekend_only_request_rejected(db):
    alice = _alice(db)
    # 2026-06-13 is a Saturday: zero working days, so it must not be bookable.
    errors = validate_request(db, alice, "personal", date(2026, 6, 13), date(2026, 6, 13), TODAY)
    assert "working day" in errors.get("start_date", "")
    assert "leave_type" not in errors  # not a balance error


def test_holiday_only_request_rejected(db):
    alice = _alice(db)
    upsert_holiday(db, date(2026, 6, 10), "Company holiday")  # a Wednesday
    errors = validate_request(db, alice, "sick", date(2026, 6, 10), date(2026, 6, 10), TODAY)
    assert "working day" in errors.get("start_date", "")


def test_range_including_a_weekend_is_still_valid(db):
    alice = _alice(db)
    # Fri 2026-06-12 .. Mon 2026-06-15 spans a weekend but has 2 working days.
    errors = validate_request(db, alice, "sick", date(2026, 6, 12), date(2026, 6, 15), TODAY)
    assert errors == {}
