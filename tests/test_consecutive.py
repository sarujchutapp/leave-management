from datetime import date

from leave.db import get_employee
from leave.holidays import upsert_holiday
from leave.policy import set_policy
from leave.requests import approve_request, create_request
from leave.seed import upsert_employee
from leave.validation import validate_request

# A long-ago `today` so requests are never "in the past"; big vacation override so
# the balance check never masks the consecutive-limit check.
TODAY = date(2026, 1, 1)


def _alice(db):
    upsert_employee(db, "U_A", "Alice", None, allowances={"sick": 100, "vacation": 100})
    return get_employee(db, "U_A")


def test_long_vacation_request_blocked_by_consecutive_limit(db):
    emp = _alice(db)
    # 2026-06-01 Mon .. 2026-06-22 Mon = 22 calendar days > 15-day cap
    errors = validate_request(db, emp, "vacation", date(2026, 6, 1), date(2026, 6, 22), TODAY)
    assert "consecutive" in errors.get("start_date", "")


def test_short_vacation_request_passes(db):
    emp = _alice(db)
    # Mon-Fri (run extends only over the surrounding weekends -> 9 days <= 15)
    errors = validate_request(db, emp, "vacation", date(2026, 6, 8), date(2026, 6, 12), TODAY)
    assert errors == {}


def test_existing_leave_bridged_by_weekend_extends_run(db):
    emp = _alice(db)
    rid = create_request(db, "U_A", "vacation", date(2026, 6, 1), date(2026, 6, 5), None)
    approve_request(db, rid)  # Mon-Fri approved
    emp = get_employee(db, "U_A")
    # New Mon-Fri the next week; the weekend bridges them -> 16-day run > 15.
    errors = validate_request(db, emp, "vacation", date(2026, 6, 8), date(2026, 6, 12), TODAY)
    assert "consecutive" in errors.get("start_date", "")


def test_half_day_request_not_capped(db):
    emp = _alice(db)
    rid = create_request(db, "U_A", "vacation", date(2026, 6, 1), date(2026, 6, 12), None)
    approve_request(db, rid)  # long existing leave
    emp = get_employee(db, "U_A")
    # A half-day is a 'present' day, so it bounds rather than fills — never blocked.
    errors = validate_request(
        db, emp, "vacation", date(2026, 6, 15), date(2026, 6, 15), TODAY, half="morning"
    )
    assert "start_date" not in errors


def test_sick_request_not_capped(db):
    emp = _alice(db)
    # A long sick stretch is not itself subject to the (vacation-only) cap.
    errors = validate_request(db, emp, "sick", date(2026, 6, 1), date(2026, 6, 22), TODAY)
    assert "start_date" not in errors


def test_sick_leave_extends_a_vacation_run(db):
    emp = _alice(db)
    rid = create_request(db, "U_A", "sick", date(2026, 6, 1), date(2026, 6, 12), None)
    approve_request(db, rid)  # existing SICK fills the run
    emp = get_employee(db, "U_A")
    errors = validate_request(db, emp, "vacation", date(2026, 6, 15), date(2026, 6, 19), TODAY)
    assert "consecutive" in errors.get("start_date", "")


def test_holiday_extends_run(db):
    set_policy(
        db,
        allowances={"sick": 30, "vacation": 10, "personal": 5},
        consecutive_limit={"vacation": 5},
    )
    emp = _alice(db)
    # Without holidays the Mon-Tue run is 4 days (<=5); two midweek holidays push it to 6.
    upsert_holiday(db, date(2026, 6, 10), "h1")  # Wed
    upsert_holiday(db, date(2026, 6, 11), "h2")  # Thu
    emp = get_employee(db, "U_A")
    errors = validate_request(db, emp, "vacation", date(2026, 6, 8), date(2026, 6, 9), TODAY)
    assert "consecutive" in errors.get("start_date", "")
