from leave.db import get_employee
from leave.seed import DEFAULT_ALLOWANCES, upsert_employee


def test_get_employee_returns_none_when_absent(conn):
    assert get_employee(conn, "U_NOBODY") is None


def test_get_employee_returns_row(conn):
    upsert_employee(conn, "U_BOSS", "Boss", None)
    upsert_employee(conn, "U_ALICE", "Alice", "U_BOSS")

    emp = get_employee(conn, "U_ALICE")
    assert emp["real_name"] == "Alice"
    assert emp["manager_id"] == "U_BOSS"
    assert emp["allowances"] == DEFAULT_ALLOWANCES


def test_null_manager_is_preserved(conn):
    upsert_employee(conn, "U_BOSS", "Boss", None)
    emp = get_employee(conn, "U_BOSS")
    assert emp["manager_id"] is None
