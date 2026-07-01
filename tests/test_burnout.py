"""Pure-function tests for the burnout measures. Hand-built inputs only — no DB,
no Slack. 2026-01-01 is a Thursday, which the working-day arithmetic relies on."""

from datetime import date

from leave.burnout import expiring_quota, longest_working_stretch, no_break_stretch

TODAY = date(2026, 6, 24)  # a Wednesday


def test_stretch_is_days_since_last_taken_leave():
    # Backward-looking: days actually gone without time off, last break to today.
    stretch = no_break_stretch(TODAY, date(2026, 3, 1))
    assert stretch == (TODAY - date(2026, 3, 1)).days


def test_stretch_ignores_breaks_booked_ahead():
    # A break booked for the future is relief, not time endured — the same as
    # having nothing booked, the count still runs only up to today.
    assert no_break_stretch(TODAY, date(2026, 3, 1)) == (TODAY - date(2026, 3, 1)).days


def test_never_taken_leave_anchors_at_year_start():
    # Handled sensibly: the stretch opens at the start of the year, not an error.
    stretch = no_break_stretch(TODAY, None)
    assert stretch == (TODAY - date(2026, 1, 1)).days


def test_never_taken_leave_anchors_at_the_leave_period_start():
    # With a non-1-Jan leave year, the stretch opens at the current period start,
    # not the calendar-year start.
    stretch = no_break_stretch(TODAY, None, period_start=date(2026, 4, 13))
    assert stretch == (TODAY - date(2026, 4, 13)).days


def test_expiring_quota_is_remaining_beyond_the_carry_cap():
    # Holds 12 vacation days, only 5 may carry over: 7 expire at year-end.
    assert expiring_quota(12, 5) == 7


def test_expiring_quota_is_zero_when_within_the_cap():
    # Holds fewer than the cap: everything carries over, nothing expires.
    assert expiring_quota(3, 5) == 0


def test_expiring_quota_floors_at_the_cap_boundary():
    # Exactly at the cap: the whole balance carries, so nothing expires.
    assert expiring_quota(5, 5) == 0


def test_working_stretch_spans_weekends_but_resets_on_leave():
    # Feb 2-27. A week of leave (Feb 16-20) splits the window. The first run is two
    # full weeks (Feb 2-13) — 10 working days, the intervening weekend spanned, not
    # reset — then leave resets it; the trailing week (Feb 23-27) is only 5.
    leave = [(date(2026, 2, 16), date(2026, 2, 20))]
    stretch = longest_working_stretch(date(2026, 2, 2), date(2026, 2, 27), leave, set())
    assert stretch == 10


def test_working_stretch_holiday_spans_run_but_is_not_counted():
    # A single Mon-Fri week (Mar 2-6) with a midweek holiday (Wed Mar 4): the
    # holiday doesn't reset the run, but it isn't a working day, so the week
    # counts 4 working days, not 5.
    stretch = longest_working_stretch(
        date(2026, 3, 2), date(2026, 3, 6), [], {date(2026, 3, 4)}
    )
    assert stretch == 4
