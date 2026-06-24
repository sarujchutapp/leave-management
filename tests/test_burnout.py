"""Pure-function tests for the burnout measures. Hand-built inputs only — no DB,
no Slack. 2026-01-01 is a Thursday, which the working-day arithmetic relies on."""

from datetime import date

from leave.burnout import expiring_quota, longest_working_stretch, no_break_stretch

TODAY = date(2026, 6, 24)  # a Wednesday


def test_stretch_spans_last_taken_to_next_booked():
    # A break taken in the past and one booked ahead: the stretch is the whole
    # gap the person endures between the two, in calendar days.
    stretch = no_break_stretch(TODAY, date(2026, 3, 1), date(2026, 9, 1))
    assert stretch == (date(2026, 9, 1) - date(2026, 3, 1)).days


def test_stretch_runs_to_today_when_nothing_booked_ahead():
    # No relief in sight: the dry spell is measured from the last break to today.
    stretch = no_break_stretch(TODAY, date(2026, 3, 1), None)
    assert stretch == (TODAY - date(2026, 3, 1)).days


def test_never_taken_leave_anchors_at_year_start():
    # Handled sensibly: the stretch opens at the start of the year, not an error.
    stretch = no_break_stretch(TODAY, None, None)
    assert stretch == (TODAY - date(2026, 1, 1)).days


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
