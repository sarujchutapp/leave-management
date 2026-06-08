from datetime import date

from leave.balance import count_weekdays


def test_friday_to_monday_counts_two_weekdays():
    # Fri 2026-06-12 .. Mon 2026-06-15 -> Fri + Mon = 2
    assert count_weekdays(date(2026, 6, 12), date(2026, 6, 15)) == 2


def test_single_weekday():
    assert count_weekdays(date(2026, 6, 10), date(2026, 6, 10)) == 1


def test_weekend_only_is_zero():
    # Sat + Sun
    assert count_weekdays(date(2026, 6, 13), date(2026, 6, 14)) == 0


def test_full_week():
    # Mon .. Sun -> 5 weekdays
    assert count_weekdays(date(2026, 6, 8), date(2026, 6, 14)) == 5


def test_end_before_start_is_zero():
    assert count_weekdays(date(2026, 6, 15), date(2026, 6, 10)) == 0
