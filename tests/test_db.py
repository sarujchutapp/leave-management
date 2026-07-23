from leave.db import get_employee
from leave.seed import upsert_employee


def test_get_employee_returns_none_when_absent(db):
    assert get_employee(db, "U_NOBODY") is None


def test_get_employee_returns_row(db):
    upsert_employee(db, "U_BOSS", "Boss", None)
    upsert_employee(db, "U_ALICE", "Alice", "U_BOSS")

    emp = get_employee(db, "U_ALICE")
    assert emp["real_name"] == "Alice"
    assert emp["manager_id"] == "U_BOSS"
    # No per-person allowances by default — balances read the central policy.
    assert "allowances" not in emp


def test_null_manager_is_preserved(db):
    upsert_employee(db, "U_BOSS", "Boss", None)
    emp = get_employee(db, "U_BOSS")
    assert emp["manager_id"] is None


def test_approval_round_trips(db):
    upsert_employee(db, "U_A", "Alice", None, approval="approval-needed")
    assert get_employee(db, "U_A")["approval"] == "approval-needed"
    upsert_employee(db, "U_A", "Alice", None, approval="auto")
    assert get_employee(db, "U_A")["approval"] == "auto"


def test_approval_absent_by_default(db):
    # No backfill: an employee written without an approval carries no such field.
    upsert_employee(db, "U_A", "Alice", None)
    assert "approval" not in get_employee(db, "U_A")
