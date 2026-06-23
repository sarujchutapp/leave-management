"""Pure-function tests for the longest-break finder. Hand-built inputs only —
no DB, no Slack. June 2026 starts on a Monday (2026-06-01 = Mon), which the
date arithmetic below relies on."""

from datetime import date

from leave.optimizer import longest_break

YEAR_END = date(2026, 12, 31)


def test_bridges_weekends_into_longest_run():
    # balance 5, cap 9, no holidays/leave. The best break is one Mon-Fri week:
    # 5 vacation days sandwiched by both weekends = 9 days off in a row.
    brk = longest_break(date(2026, 6, 1), YEAR_END, 5, set(), [], 9)
    assert brk.book_start == date(2026, 6, 1)
    assert brk.book_end == date(2026, 6, 5)
    assert brk.cost == 5
    assert brk.span_start == date(2026, 5, 30)
    assert brk.span_end == date(2026, 6, 7)
    assert brk.span_days == 9


def test_span_never_exceeds_cap():
    # Even with balance to spare (10), the suggested span is bounded by the cap (9).
    brk = longest_break(date(2026, 6, 1), YEAR_END, 10, set(), [], 9)
    assert brk.span_days == 9
    assert brk.cost == 5  # min quota to fill a 9-day window with no holidays


def test_builds_around_existing_booking():
    # Existing Thu-Fri (06-04/05) leave. Balance 3 books the preceding Mon-Wed,
    # which abuts the existing leave directly and grabs both surrounding weekends:
    # 3 vacation days extend the existing booking into one 9-day absence.
    existing = [(date(2026, 6, 4), date(2026, 6, 5))]
    brk = longest_break(date(2026, 5, 1), YEAR_END, 3, set(), existing, 15)
    assert brk.book_start == date(2026, 6, 1)
    assert brk.book_end == date(2026, 6, 3)
    assert brk.cost == 3
    assert brk.span_start == date(2026, 5, 30)
    assert brk.span_end == date(2026, 6, 7)
    assert brk.span_days == 9


def test_tiebreak_prefers_least_quota():
    # Two 9-day windows: a plain Mon-Fri week (cost 5) and a later week with a
    # midweek holiday (cost 4). Same span -> the cheaper one wins.
    holidays = {date(2026, 6, 17)}  # Wed of the 06-15..06-19 week
    brk = longest_break(date(2026, 6, 1), YEAR_END, 5, holidays, [], 9)
    assert brk.span_days == 9
    assert brk.cost == 4
    assert brk.book_start == date(2026, 6, 15)
    assert brk.book_end == date(2026, 6, 19)


def test_never_spends_a_working_day_next_year():
    # From late December only Mon-Thu (Dec 28-31) are bookable working days; the
    # New-Year holiday + weekend let the span spill into January for free.
    holidays = {date(2027, 1, 1)}
    brk = longest_break(date(2026, 12, 28), YEAR_END, 10, holidays, [], 15)
    assert brk.book_start == date(2026, 12, 28)
    assert brk.book_end == date(2026, 12, 31)
    assert brk.book_end.year == 2026  # no booked working day in 2027
    assert brk.cost == 4
    assert brk.span_end == date(2027, 1, 3)  # spilled into Jan via free days
    assert brk.span_days == 9


def test_no_balance_returns_none():
    assert longest_break(date(2026, 6, 1), YEAR_END, 0, set(), [], 15) is None
