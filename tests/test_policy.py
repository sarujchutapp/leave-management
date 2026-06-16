from datetime import date

from leave.db import get_employee
from leave.policy import get_policy, set_policy
from leave.requests import remaining_balance, remaining_balances
from leave.seed import upsert_employee

TODAY = date(2026, 6, 8)


def test_central_policy_change_affects_employee_without_override(db):
    # An employee created with no per-person allowances reads the central policy.
    upsert_employee(db, "U_B", "Bob", None)
    set_policy(db, allowances={"sick": 30, "vacation": 12, "personal": 5})
    emp = get_employee(db, "U_B")
    assert remaining_balance(db, emp, "vacation", TODAY) == 12


def test_employee_override_takes_precedence_over_central(db):
    upsert_employee(db, "U_C", "Cara", None, allowances={"vacation": 20})
    set_policy(db, allowances={"sick": 30, "vacation": 12, "personal": 5})
    emp = get_employee(db, "U_C")
    assert remaining_balance(db, emp, "vacation", TODAY) == 20


def test_remaining_balances_mixes_override_and_central(db):
    # Override only vacation; sick/personal fall back to central.
    upsert_employee(db, "U_C", "Cara", None, allowances={"vacation": 20})
    set_policy(db, allowances={"sick": 30, "vacation": 12, "personal": 5})
    emp = get_employee(db, "U_C")
    assert remaining_balances(db, emp, TODAY) == {"sick": 30, "vacation": 20, "personal": 5}


def test_policy_holds_caps_centrally(db):
    set_policy(
        db,
        allowances={"sick": 30, "vacation": 10, "personal": 5},
        max_carry_over={"vacation": 6},
        max_total={"vacation": 16},
        consecutive_limit={"vacation": 15},
    )
    p = get_policy(db)
    assert p["max_carry_over"]["vacation"] == 6
    assert p["max_total"]["vacation"] == 16
    assert p["consecutive_limit"]["vacation"] == 15


def test_get_policy_falls_back_to_defaults_when_unseeded(db):
    p = get_policy(db)
    assert p["allowances"]["vacation"] == 10
    assert p["consecutive_limit"]["vacation"] == 15
