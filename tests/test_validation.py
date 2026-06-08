from datetime import date

from leave.db import get_employee
from leave.requests import create_request
from leave.seed import upsert_employee
from leave.validation import validate_request

TODAY = date(2026, 6, 8)


def _alice(conn):
    upsert_employee(conn, "U_ALICE", "Alice", None, {"sick": 30, "vacation": 2, "personal": 5})
    return get_employee(conn, "U_ALICE")


def test_valid_request_has_no_errors(conn):
    alice = _alice(conn)
    errors = validate_request(conn, alice, "vacation", date(2026, 6, 10), date(2026, 6, 11), TODAY)
    assert errors == {}


def test_end_before_start(conn):
    alice = _alice(conn)
    errors = validate_request(conn, alice, "vacation", date(2026, 6, 12), date(2026, 6, 10), TODAY)
    assert "end_date" in errors


def test_start_in_past(conn):
    alice = _alice(conn)
    errors = validate_request(conn, alice, "vacation", date(2026, 6, 1), date(2026, 6, 2), TODAY)
    assert "start_date" in errors


def test_exceeds_balance(conn):
    alice = _alice(conn)  # vacation allowance = 2
    # Wed-Fri = 3 weekdays > 2
    errors = validate_request(conn, alice, "vacation", date(2026, 6, 10), date(2026, 6, 12), TODAY)
    assert "leave_type" in errors


def test_overlap(conn):
    alice = _alice(conn)
    create_request(conn, "U_ALICE", "sick", date(2026, 6, 10), date(2026, 6, 11), None)
    errors = validate_request(conn, alice, "sick", date(2026, 6, 11), date(2026, 6, 12), TODAY)
    assert "end_date" in errors
