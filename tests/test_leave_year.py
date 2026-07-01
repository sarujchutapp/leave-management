from datetime import date

from leave.leave_year import (
    current_period,
    last_reset,
    leave_period,
    next_reset,
    period_key,
    reset_transition,
)


def test_default_jan1_is_the_calendar_year():
    # 1 Jan reset: the period containing any mid-year day is that whole calendar year.
    start, end = leave_period(date(2026, 6, 1), 1, 1)
    assert start == date(2026, 1, 1)
    assert end == date(2027, 1, 1)  # exclusive -> last counted day is 31 Dec 2026


def test_next_reset_is_strictly_after_today():
    # On the reset day itself, the next reset is a year out, not today.
    assert next_reset(date(2026, 1, 1), 1, 1) == date(2027, 1, 1)
    assert next_reset(date(2026, 6, 1), 4, 13) == date(2027, 4, 13)  # Apr 13 already passed
    assert next_reset(date(2026, 3, 1), 4, 13) == date(2026, 4, 13)  # Apr 13 still ahead


def test_last_reset_is_on_or_before_today():
    assert last_reset(date(2026, 1, 1), 1, 1) == date(2026, 1, 1)  # inclusive on the day
    assert last_reset(date(2026, 6, 1), 4, 13) == date(2026, 4, 13)
    assert last_reset(date(2026, 3, 1), 4, 13) == date(2025, 4, 13)


def test_current_period_has_positive_length():
    start, end = leave_period(date(2026, 6, 1), 4, 13)
    assert start < end
    assert start <= date(2026, 6, 1) < end


def test_period_over_a_non_jan1_reset_spans_two_calendar_years():
    # An Apr-13 leave year runs Apr 13 -> Apr 13 next year, crossing the year boundary.
    start, end = leave_period(date(2026, 6, 1), 4, 13)
    assert start == date(2026, 4, 13)
    assert end == date(2027, 4, 13)


def test_transition_to_a_date_ahead_this_year_is_a_stub():
    # Today 1 Mar, currently 1-Jan (period ends next 1 Jan). Move to Apr 13 (still
    # ahead this year): the new reset lands before the old end -> a shorter stub.
    current_end = next_reset(date(2026, 3, 1), 1, 1)  # 2027-01-01
    new_end, kind = reset_transition(date(2026, 3, 1), current_end, 4, 13)
    assert new_end == date(2026, 4, 13)
    assert kind == "stub"


def test_transition_to_a_date_already_passed_this_year_is_a_stretch():
    # Today 1 Jun, currently 1-Jan. Move to Apr 13 (already passed): the new reset is
    # a year out, past the old end -> a longer stretch.
    current_end = next_reset(date(2026, 6, 1), 1, 1)  # 2027-01-01
    new_end, kind = reset_transition(date(2026, 6, 1), current_end, 4, 13)
    assert new_end == date(2027, 4, 13)
    assert kind == "stretch"


def test_transition_to_the_same_date_is_unchanged():
    current_end = next_reset(date(2026, 6, 1), 1, 1)
    _, kind = reset_transition(date(2026, 6, 1), current_end, 1, 1)
    assert kind == "unchanged"


def test_feb29_reset_clamps_to_feb28_in_a_common_year():
    # 2027 is not a leap year: a 29 Feb reset still fires once, on 28 Feb.
    assert next_reset(date(2027, 1, 15), 2, 29) == date(2027, 2, 28)
    assert next_reset(date(2028, 1, 15), 2, 29) == date(2028, 2, 29)  # leap year keeps the 29th


def test_period_key_is_byte_compatible_year_for_jan1():
    assert period_key(date(2026, 1, 1)) == "2026"


def test_period_key_is_iso_for_non_jan1_and_unique_across_a_stub():
    # Two resets in one calendar year (1 Jan then 13 Apr after a stub) key distinctly.
    assert period_key(date(2026, 4, 13)) == "2026-04-13"
    assert period_key(date(2026, 1, 1)) != period_key(date(2026, 4, 13))


def test_current_period_without_a_pin_is_the_plain_recurrence():
    assert current_period(date(2026, 6, 1), 1, 1) == leave_period(date(2026, 6, 1), 1, 1)


def test_current_period_holds_a_pinned_stretch_then_advances_aligned():
    # Pinned stretch period: started 1 Jan 2026, reset moved to 13 Apr so it now ends
    # 13 Apr 2027. Until then the pinned start holds; after, it advances a clean year.
    anchor, start = date(2027, 4, 13), date(2026, 1, 1)
    assert current_period(date(2026, 6, 1), 4, 13, anchor, start) == (start, anchor)
    # A day past the anchor: the pin is spent, the recurrence takes over.
    assert current_period(date(2027, 6, 1), 4, 13, anchor, start) == (
        date(2027, 4, 13),
        date(2028, 4, 13),
    )
