from datetime import date

from leave.db import get_employee
from leave.requests import (
    approve_request,
    approved_weekdays_this_year,
    cancel_request,
    create_request,
    get_request,
    has_overlap,
    remaining_balance,
    remaining_balances,
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
    approve_request(db, rid)
    # Wed-Fri = 3 weekdays
    assert remaining_balance(db, alice, "vacation", TODAY) == 7


def test_remaining_balances_returns_all_types_from_one_query(db):
    # The /dayoff modal path: every type's balance from a single by_employee query.
    alice = _alice(db)
    rid = create_request(db, "U_ALICE", "vacation", date(2026, 6, 10), date(2026, 6, 12), None)
    approve_request(db, rid)  # Wed-Fri = 3 weekdays
    assert remaining_balances(db, alice, TODAY) == {"sick": 30, "vacation": 7, "personal": 5}


def test_approved_in_other_year_does_not_count(db):
    _alice(db)
    rid = create_request(db, "U_ALICE", "vacation", date(2025, 6, 10), date(2025, 6, 12), None)
    approve_request(db, rid)
    assert approved_weekdays_this_year(db, "U_ALICE", "vacation", TODAY) == 0


def test_overlap_detects_pending_and_approved(db):
    _alice(db)
    create_request(db, "U_ALICE", "vacation", date(2026, 6, 10), date(2026, 6, 12), None)
    assert has_overlap(db, "U_ALICE", date(2026, 6, 11), date(2026, 6, 11)) is True
    assert has_overlap(db, "U_ALICE", date(2026, 6, 20), date(2026, 6, 21)) is False


def test_overlap_ignores_cancelled(db):
    _alice(db)
    rid = create_request(db, "U_ALICE", "vacation", date(2026, 6, 10), date(2026, 6, 12), None)
    cancel_request(db, rid)
    assert has_overlap(db, "U_ALICE", date(2026, 6, 11), date(2026, 6, 11)) is False


def test_create_request_is_pending(db):
    _alice(db)
    rid = create_request(db, "U_ALICE", "sick", date(2026, 6, 10), date(2026, 6, 10), "flu")
    row = get_request(db, rid)
    assert row["status"] == "pending"
    assert row["reason"] == "flu"
