from datetime import date

from leave.db import get_employee
from leave.requests import (
    approved_weekdays_this_year,
    create_request,
    has_overlap,
    remaining_balance,
)
from leave.seed import upsert_employee

TODAY = date(2026, 6, 8)


def _alice(conn):
    upsert_employee(conn, "U_ALICE", "Alice", None, {"sick": 30, "vacation": 10, "personal": 5})
    return get_employee(conn, "U_ALICE")


def test_remaining_balance_starts_at_allowance(conn):
    alice = _alice(conn)
    assert remaining_balance(conn, alice, "vacation", TODAY) == 10


def test_remaining_balance_subtracts_approved_weekdays(conn):
    alice = _alice(conn)
    rid = create_request(conn, "U_ALICE", "vacation", date(2026, 6, 10), date(2026, 6, 12), None)
    conn.execute("UPDATE requests SET status='approved' WHERE id=%s", (rid,))
    # Wed-Fri = 3 weekdays
    assert remaining_balance(conn, alice, "vacation", TODAY) == 7


def test_approved_in_other_year_does_not_count(conn):
    _alice(conn)
    rid = create_request(conn, "U_ALICE", "vacation", date(2025, 6, 10), date(2025, 6, 12), None)
    conn.execute("UPDATE requests SET status='approved' WHERE id=%s", (rid,))
    assert approved_weekdays_this_year(conn, "U_ALICE", "vacation", TODAY) == 0


def test_overlap_detects_pending_and_approved(conn):
    _alice(conn)
    create_request(conn, "U_ALICE", "vacation", date(2026, 6, 10), date(2026, 6, 12), None)
    assert has_overlap(conn, "U_ALICE", date(2026, 6, 11), date(2026, 6, 11)) is True
    assert has_overlap(conn, "U_ALICE", date(2026, 6, 20), date(2026, 6, 21)) is False


def test_overlap_ignores_cancelled(conn):
    _alice(conn)
    rid = create_request(conn, "U_ALICE", "vacation", date(2026, 6, 10), date(2026, 6, 12), None)
    conn.execute("UPDATE requests SET status='cancelled' WHERE id=%s", (rid,))
    assert has_overlap(conn, "U_ALICE", date(2026, 6, 11), date(2026, 6, 11)) is False


def test_create_request_is_pending(conn):
    _alice(conn)
    rid = create_request(conn, "U_ALICE", "sick", date(2026, 6, 10), date(2026, 6, 10), "flu")
    row = conn.execute("SELECT status, reason FROM requests WHERE id=%s", (rid,)).fetchone()
    assert row["status"] == "pending"
    assert row["reason"] == "flu"
