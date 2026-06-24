"""Leave Optimizer — pure suggestion math over plain inputs (no DB, no Slack).

The first job is the **longest-break finder**: given the caller's remaining
vacation balance, the company holiday set, their existing full-day leave, the
consecutive limit, and the horizon (today .. year_end), find the longest
continuous absences they can still book this calendar year — either the single
best (`longest_break`) or the top few distinct options (`top_breaks`).

Accounting mirrors `requests.continuous_absence_length`: weekends, holidays and
existing full-day leave are non-working days that fill a run; a worked day (a
weekday that is neither holiday nor leave) bounds it. The break is the set of
working days the caller would actually book (the only days that cost quota); the
span is the resulting continuous absence those days create, bridges included.
"""

from collections import namedtuple
from datetime import timedelta

# A suggested break. `book_start`/`book_end` is the vacation range to file — the
# only days that cost quota. `span_*` is the resulting continuous absence
# (calendar days off in a row), including bridging weekends/holidays and any
# existing leave the break extends.
LeaveBreak = namedtuple("LeaveBreak", "book_start book_end cost span_start span_end span_days")

_ONE = timedelta(days=1)


def _is_working(d, holidays, ranges):
    """A day actually worked: a weekday that is neither holiday nor existing
    full-day leave. Such a day bounds a continuous absence."""
    if d.weekday() >= 5 or d in holidays:
        return False
    return not any(s <= d <= e for s, e in ranges)


def _sort_key(brk):
    # Longest span, then least quota spent, then earliest — so the chosen break
    # is the most generous, cheapest, soonest one.
    return (-brk.span_days, brk.cost, brk.book_start)


def _all_candidates(today, year_end, balance, holidays, existing_ranges, cap):
    """Every bookable break in [today, year_end]: a working-day-bounded booking
    that doesn't overlap existing leave, costs at most `balance`, spends no
    working day past `year_end`, and yields a continuous-absence span within
    `cap` (so each always passes `validate_request`)."""
    if balance <= 0:
        return []

    def worked(d, b_start, b_end):
        # Like _is_working, but the proposed booking also makes a day non-working.
        if b_start <= d <= b_end:
            return False
        return _is_working(d, holidays, existing_ranges)

    def overlaps_existing(b_start, b_end):
        return any(s <= b_end and e >= b_start for s, e in existing_ranges)

    candidates = []
    b_start = today
    while b_start <= year_end:
        # Start on a working day: a leading weekend/holiday is already non-working,
        # so it would add nothing and only muddy the booked dates.
        if not _is_working(b_start, holidays, existing_ranges):
            b_start += _ONE
            continue

        b_end, cost = b_start, 0
        # A span of L calendar days needs a booking no longer than L, and the span
        # can't exceed `cap`, so the booking can't either.
        while b_end <= year_end and (b_end - b_start).days < cap:
            if overlaps_existing(b_start, b_end):
                break
            ends_on_working = _is_working(b_end, holidays, existing_ranges)
            if ends_on_working:
                cost += 1
            if cost > balance:
                break
            # Only consider candidates that end on a working day (a trailing
            # weekend/holiday would be a non-canonical framing of a shorter booking).
            if ends_on_working:
                span_start, span_end = b_start, b_end
                while not worked(span_start - _ONE, b_start, b_end):
                    span_start -= _ONE
                while not worked(span_end + _ONE, b_start, b_end):
                    span_end += _ONE
                span_days = (span_end - span_start).days + 1
                if span_days <= cap:
                    candidates.append(
                        LeaveBreak(b_start, b_end, cost, span_start, span_end, span_days)
                    )
            b_end += _ONE
        b_start += _ONE

    return candidates


def _span_overlap_days(a, b):
    """Calendar days the two breaks' days-off spans share (0 if disjoint)."""
    lo, hi = max(a.span_start, b.span_start), min(a.span_end, b.span_end)
    return max(0, (hi - lo).days + 1)


def _distinct_options(a, b):
    """Whether two breaks are distinct options rather than framings of the same
    break: their days-off spans must differ on more days than they share — the
    days in exactly one span outnumber the days in both. So options may share a
    boundary weekend, but a break that mostly retraces another collapses to the
    better-ranked one."""
    overlap = _span_overlap_days(a, b)
    non_overlap = a.span_days + b.span_days - 2 * overlap
    return non_overlap > overlap


def top_breaks(today, year_end, balance, holidays, existing_ranges, cap, limit=3):
    """Up to `limit` distinct break options, longest-first (then least quota,
    then earliest). Two options are kept apart only when their days-off spans
    differ on more days than they share (see `_distinct_options`); otherwise the
    better-ranked one is kept and the other dropped. Degrades to fewer (or none)
    when fewer distinct breaks exist."""
    ranked = sorted(
        _all_candidates(today, year_end, balance, holidays, existing_ranges, cap), key=_sort_key
    )
    chosen = []
    for cand in ranked:
        if all(_distinct_options(cand, c) for c in chosen):
            chosen.append(cand)
            if len(chosen) == limit:
                break
    return chosen


def longest_break(today, year_end, balance, holidays, existing_ranges, cap):
    """The single longest continuous absence the caller can still book in
    [today, year_end], or None if nothing is bookable."""
    best = top_breaks(today, year_end, balance, holidays, existing_ranges, cap, limit=1)
    return best[0] if best else None
