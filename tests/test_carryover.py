from datetime import date

from leave.db import get_employee
from leave.holidays import upsert_holiday
from leave.policy import set_policy
from leave.requests import (
    approve_request,
    create_request,
    recompute_carry_in,
    remaining_balance,
    remaining_balances,
)
from leave.seed import upsert_employee


def _approve_vacation(db, emp_id, start, end):
    rid = create_request(db, emp_id, "vacation", start, end, None)
    approve_request(db, rid)


def test_new_hire_has_no_phantom_carry(db):
    upsert_employee(db, "U_N", "New", None)  # base vacation 10
    emp = get_employee(db, "U_N")
    # First ever access (2028): carry_in seeds to 0, remaining is just the base.
    assert remaining_balance(db, emp, "vacation", date(2028, 6, 1)) == 10
    assert get_employee(db, "U_N").get("carry_in") == {"2028": 0}


def test_carry_rolls_prior_year_leftover_capped(db):
    # base 10, max_carry 5, max_total 15. Use 4 vacation days in 2026 -> leftover 6 -> carry 5.
    upsert_employee(db, "U_A", "Alice", None)
    _approve_vacation(db, "U_A", date(2026, 6, 8), date(2026, 6, 11))  # Mon-Thu = 4
    emp = get_employee(db, "U_A")
    assert remaining_balance(db, emp, "vacation", date(2026, 6, 1)) == 6  # seeds carry_in[2026]=0
    emp = get_employee(db, "U_A")
    assert remaining_balance(db, emp, "vacation", date(2027, 6, 1)) == 15  # min(10+min(6,5),15)
    assert get_employee(db, "U_A")["carry_in"]["2027"] == 5


def test_max_total_caps_in_year_availability(db):
    set_policy(
        db,
        allowances={"sick": 30, "vacation": 10, "personal": 5},
        max_carry_over={"vacation": 5},
        max_total={"vacation": 12},
    )
    upsert_employee(db, "U_A", "Alice", None)  # no 2026 usage -> leftover 10 -> carry 5
    emp = get_employee(db, "U_A")
    remaining_balance(db, emp, "vacation", date(2026, 6, 1))  # seed 2026
    emp = get_employee(db, "U_A")
    # available = min(10 + min(10,5), 12) = min(15, 12) = 12
    assert remaining_balance(db, emp, "vacation", date(2027, 6, 1)) == 12


def test_sick_does_not_carry(db):
    upsert_employee(db, "U_A", "Alice", None)
    rid = create_request(db, "U_A", "sick", date(2026, 6, 8), date(2026, 6, 11), None)
    approve_request(db, rid)
    emp = get_employee(db, "U_A")
    assert remaining_balance(db, emp, "sick", date(2027, 6, 1)) == 30  # resets, no carry


def test_carry_in_is_idempotent(db):
    upsert_employee(db, "U_A", "Alice", None)
    _approve_vacation(db, "U_A", date(2026, 6, 8), date(2026, 6, 11))
    emp = get_employee(db, "U_A")
    remaining_balance(db, emp, "vacation", date(2026, 6, 1))
    emp = get_employee(db, "U_A")
    first = remaining_balance(db, emp, "vacation", date(2027, 6, 1))
    emp = get_employee(db, "U_A")
    second = remaining_balance(db, emp, "vacation", date(2027, 6, 1))
    assert first == second == 15
    assert get_employee(db, "U_A")["carry_in"] == {"2026": 0, "2027": 5}


def test_within_year_retroactive_holiday_still_refunds_under_carry(db):
    upsert_employee(db, "U_A", "Alice", None)
    _approve_vacation(db, "U_A", date(2027, 6, 8), date(2027, 6, 10))  # Mon-Wed = 3 used in 2027
    emp = get_employee(db, "U_A")
    assert remaining_balance(db, emp, "vacation", date(2027, 6, 1)) == 7  # 10 - 3
    upsert_holiday(db, date(2027, 6, 9), "midweek")  # retroactive within-year
    emp = get_employee(db, "U_A")
    assert remaining_balance(db, emp, "vacation", date(2027, 6, 1)) == 8  # used drops to 2


def test_recompute_rebuilds_after_prior_year_change(db):
    upsert_employee(db, "U_A", "Alice", None)
    emp = get_employee(db, "U_A")
    remaining_balance(db, emp, "vacation", date(2026, 6, 1))  # seed 2026:0
    emp = get_employee(db, "U_A")
    remaining_balance(db, emp, "vacation", date(2027, 6, 1))  # no 2026 usage -> carry_in[2027]=5
    assert get_employee(db, "U_A")["carry_in"]["2027"] == 5

    # Approve 8 vacation days in 2026 after the fact, then recompute 2027.
    _approve_vacation(db, "U_A", date(2026, 6, 8), date(2026, 6, 17))  # 8 weekdays
    recompute_carry_in(db, get_employee(db, "U_A"), 2027)
    assert get_employee(db, "U_A")["carry_in"]["2027"] == 2  # leftover 10-8=2 -> min(2,5)


# --- Configurable leave-year reset date (issue #56): a non-1-Jan reset. ---


def test_balance_over_a_non_jan_period_resets_on_the_configured_date(db):
    # Reset on 13 Apr: the leave period runs Apr 13 -> Apr 13 next year.
    set_policy(db, reset_month=4, reset_day=13)
    upsert_employee(db, "U_A", "Alice", None)
    _approve_vacation(db, "U_A", date(2026, 6, 8), date(2026, 6, 11))  # Mon-Thu = 4, in the period
    emp = get_employee(db, "U_A")
    # Still within the period at year-end: usage counts, nothing resets on 31 Dec.
    assert remaining_balance(db, emp, "vacation", date(2026, 12, 31)) == 6
    emp = get_employee(db, "U_A")
    # On the reset date the period turns over: prior usage no longer counts and the
    # unused days carry in (min(leftover 6, max_carry 5) = 5 -> min(10+5, 15) = 15).
    assert remaining_balance(db, emp, "vacation", date(2027, 4, 13)) == 15


def test_carry_in_keyed_per_reset_period_and_idempotent(db):
    set_policy(db, reset_month=4, reset_day=13)
    upsert_employee(db, "U_A", "Alice", None)
    _approve_vacation(db, "U_A", date(2026, 6, 8), date(2026, 6, 11))  # 4 used in the 2026 period
    emp = get_employee(db, "U_A")
    remaining_balance(db, emp, "vacation", date(2026, 12, 31))  # seed the Apr-2026 period at 0
    emp = get_employee(db, "U_A")
    first = remaining_balance(db, emp, "vacation", date(2027, 4, 13))
    emp = get_employee(db, "U_A")
    second = remaining_balance(db, emp, "vacation", date(2027, 4, 13))
    assert first == second == 15  # advancing across the reset is idempotent
    # Keyed per reset period by start date, unique from any calendar-year key.
    assert get_employee(db, "U_A")["carry_in"] == {"2026-04-13": 0, "2027-04-13": 5}


def test_used_reads_holidays_across_a_period_spanning_two_calendar_years(db):
    set_policy(db, reset_month=4, reset_day=13)
    upsert_employee(db, "U_A", "Alice", None)
    # Leave in Jan 2027 falls in the Apr-2026 -> Apr-2027 period, not a calendar year.
    _approve_vacation(db, "U_A", date(2027, 1, 5), date(2027, 1, 7))  # Tue-Thu = 3
    emp = get_employee(db, "U_A")
    assert remaining_balance(db, emp, "vacation", date(2027, 2, 1)) == 7  # 10 - 3
    upsert_holiday(db, date(2027, 1, 6), "midweek")  # inside the period, second calendar year
    emp = get_employee(db, "U_A")
    assert remaining_balance(db, emp, "vacation", date(2027, 2, 1)) == 8  # used drops to 2
