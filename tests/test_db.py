from leave.db import get_employee
from leave.seed import DEFAULT_ALLOWANCES, upsert_employee


def test_get_employee_returns_none_when_absent(db):
    assert get_employee(db, "U_NOBODY") is None


def test_get_employee_returns_row(db):
    upsert_employee(db, "U_BOSS", "Boss", None)
    upsert_employee(db, "U_ALICE", "Alice", "U_BOSS")

    emp = get_employee(db, "U_ALICE")
    assert emp["real_name"] == "Alice"
    assert emp["manager_id"] == "U_BOSS"
    assert emp["allowances"] == DEFAULT_ALLOWANCES


def test_null_manager_is_preserved(db):
    upsert_employee(db, "U_BOSS", "Boss", None)
    emp = get_employee(db, "U_BOSS")
    assert emp["manager_id"] is None
