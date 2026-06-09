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


def _alice(db):
    upsert_employee(db, "U_ALICE", "Alice", None, {"sick": 30, "vacation": 10, "personal": 5})
    return get_employee(db, "U_ALICE")


def test_remaining_balance_starts_at_allowance(db):
    alice = _alice(db)
    assert remaining_balance(db, alice, "vacation", TODAY) == 10


def test_remaining_balance_subtracts_approved_weekdays(db):
    alice = _alice(db)
    rid = create_request(db, "U_ALICE", "vacation", date(2026, 6, 10), date(2026, 6, 12), None)
    db.execute("UPDATE requests SET status='approved' WHERE id=%s", (rid,))
    # Wed-Fri = 3 weekdays
    assert remaining_balance(db, alice, "vacation", TODAY) == 7


def test_approved_in_other_year_does_not_count(db):
    _alice(db)
    rid = create_request(db, "U_ALICE", "vacation", date(2025, 6, 10), date(2025, 6, 12), None)
    db.execute("UPDATE requests SET status='approved' WHERE id=%s", (rid,))
    assert approved_weekdays_this_year(db, "U_ALICE", "vacation", TODAY) == 0


def test_overlap_detects_pending_and_approved(db):
    _alice(db)
    create_request(db, "U_ALICE", "vacation", date(2026, 6, 10), date(2026, 6, 12), None)
    assert has_overlap(db, "U_ALICE", date(2026, 6, 11), date(2026, 6, 11)) is True
    assert has_overlap(db, "U_ALICE", date(2026, 6, 20), date(2026, 6, 21)) is False


def test_overlap_ignores_cancelled(db):
    _alice(db)
    rid = create_request(db, "U_ALICE", "vacation", date(2026, 6, 10), date(2026, 6, 12), None)
    db.execute("UPDATE requests SET status='cancelled' WHERE id=%s", (rid,))
    assert has_overlap(db, "U_ALICE", date(2026, 6, 11), date(2026, 6, 11)) is False


def test_create_request_is_pending(db):
    _alice(db)
    rid = create_request(db, "U_ALICE", "sick", date(2026, 6, 10), date(2026, 6, 10), "flu")
    row = db.execute("SELECT status, reason FROM requests WHERE id=%s", (rid,)).fetchone()
    assert row["status"] == "pending"
    assert row["reason"] == "flu"
