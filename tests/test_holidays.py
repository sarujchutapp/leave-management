from datetime import date

from leave.balance import count_weekdays, request_days
from leave.db import get_employee
from leave.holidays import holidays_between, holidays_for_year, upsert_holiday
from leave.requests import approve_request, create_request, remaining_balance
from leave.seed import upsert_employee
from leave.validation import validate_request


def test_no_holidays_set_yet_is_empty(db):
    # Before any holiday is added, the reserved __holidays__ item doesn't exist, so
    # the system simply runs holiday-free — not an error.
    assert holidays_for_year(db, 2026) == set()
    assert holidays_between(db, date(2026, 1, 1), date(2026, 12, 31)) == set()


def test_count_weekdays_skips_a_holiday():
    # Mon 2026-06-08 .. Fri 2026-06-12 = 5 weekdays; Wed 06-10 a holiday -> 4
    holidays = {date(2026, 6, 10)}
    assert count_weekdays(date(2026, 6, 8), date(2026, 6, 12), holidays) == 4


def test_count_weekdays_unchanged_without_holidays():
    assert count_weekdays(date(2026, 6, 8), date(2026, 6, 12)) == 5


def test_half_day_on_holiday_costs_nothing():
    # A morning half on a holiday date -> 0 (holiday beats half)
    holidays = {date(2026, 6, 10)}
    assert request_days(date(2026, 6, 10), date(2026, 6, 10), "morning", holidays) == 0


def test_upsert_and_fetch_holidays_for_year(db):
    upsert_holiday(db, date(2026, 4, 13), "Songkran")
    upsert_holiday(db, date(2026, 12, 31), "New Year's Eve")
    upsert_holiday(db, date(2025, 1, 1), "old year")
    assert holidays_for_year(db, 2026) == {date(2026, 4, 13), date(2026, 12, 31)}


def test_holidays_between_spans_years(db):
    upsert_holiday(db, date(2026, 12, 31), "NYE")
    upsert_holiday(db, date(2027, 1, 1), "New Year")
    assert holidays_between(db, date(2026, 12, 30), date(2027, 1, 2)) == {
        date(2026, 12, 31),
        date(2027, 1, 1),
    }


def test_holiday_retroactively_refunds_approved_leave(db):
    upsert_employee(db, "U_A", "Alice", None)  # central vacation allowance 10
    rid = create_request(db, "U_A", "vacation", date(2026, 6, 8), date(2026, 6, 10), None)
    approve_request(db, rid)  # Mon-Wed = 3 weekdays used
    emp = get_employee(db, "U_A")
    assert remaining_balance(db, emp, "vacation", date(2026, 6, 1)) == 7

    upsert_holiday(db, date(2026, 6, 9), "midweek holiday")  # Tue, inside the range
    assert remaining_balance(db, emp, "vacation", date(2026, 6, 1)) == 8


def test_validation_excludes_holidays_from_requested_days(db):
    # Balance of 2; a Mon-Wed request normally costs 3, but a Tue holiday makes it 2 -> fits.
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 2})
    upsert_holiday(db, date(2026, 6, 9), "holiday")  # Tue
    emp = get_employee(db, "U_A")
    errors = validate_request(
        db, emp, "vacation", date(2026, 6, 8), date(2026, 6, 10), date(2026, 6, 1)
    )
    assert errors == {}
