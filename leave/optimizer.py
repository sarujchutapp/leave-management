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

from leave.absence import continuous_absence, is_worked

# A suggested break. `book_start`/`book_end` is the vacation range to file — the
# only days that cost quota. `span_*` is the resulting continuous absence
# (calendar days off in a row), including bridging weekends/holidays and any
# existing leave the break extends.
LeaveBreak = namedtuple("LeaveBreak", "book_start book_end cost span_start span_end span_days")

_ONE = timedelta(days=1)


def _as_cap(cap):
    """A None consecutive limit means the cap is disabled — an unbounded run
    (see validation.py, which treats None the same way)."""
    return float("inf") if cap is None else cap


def _sort_key(brk):
    # Longest span, then least quota spent, then earliest — so the chosen break
    # is the most generous, cheapest, soonest one.
    return (-brk.span_days, brk.cost, brk.book_start)


def _all_candidates(today, year_end, balance, holidays, existing_ranges, cap, blocked_dates):
    """Every bookable break in [today, year_end]: a working-day-bounded booking
    that doesn't overlap existing leave, costs at most `balance`, spends no
    working day past `year_end`, and yields a continuous-absence span within
    `cap` (so each always passes `validate_request`). `blocked_dates` are dates
    that may not be booked (e.g. an existing half-day) but still bound a run like
    any worked day — blocked-but-present."""
    if balance <= 0:
        return []
    cap = _as_cap(cap)

    def overlaps_existing(b_start, b_end):
        return any(s <= b_end and e >= b_start for s, e in existing_ranges)

    candidates = []
    b_start = today
    while b_start <= year_end:
        # Start on a working, non-blocked day: a leading weekend/holiday is already
        # non-working, so it would add nothing and only muddy the booked dates, and a
        # blocked date can't be booked at all.
        if not is_worked(b_start, holidays, existing_ranges) or b_start in blocked_dates:
            b_start += _ONE
            continue

        b_end, cost = b_start, 0
        # A span of L calendar days needs a booking no longer than L, and the span
        # can't exceed `cap`, so the booking can't either.
        while b_end <= year_end and (b_end - b_start).days < cap:
            if overlaps_existing(b_start, b_end) or b_end in blocked_dates:
                break
            ends_on_working = is_worked(b_end, holidays, existing_ranges)
            if ends_on_working:
                cost += 1
            if cost > balance:
                break
            # Only consider candidates that end on a working day (a trailing
            # weekend/holiday would be a non-canonical framing of a shorter booking).
            if ends_on_working:
                span_start, span_end, span_days = continuous_absence(
                    b_start, b_end, holidays, existing_ranges
                )
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


def top_breaks(
    today, year_end, balance, holidays, existing_ranges, cap, limit=3, blocked_dates=frozenset()
):
    """Up to `limit` distinct break options, longest-first (then least quota,
    then earliest). Two options are kept apart only when their days-off spans
    differ on more days than they share (see `_distinct_options`); otherwise the
    better-ranked one is kept and the other dropped. Degrades to fewer (or none)
    when fewer distinct breaks exist."""
    ranked = sorted(
        _all_candidates(today, year_end, balance, holidays, existing_ranges, cap, blocked_dates),
        key=_sort_key,
    )
    chosen = []
    for cand in ranked:
        if all(_distinct_options(cand, c) for c in chosen):
            chosen.append(cand)
            if len(chosen) == limit:
                break
    return chosen


def longest_break(today, year_end, balance, holidays, existing_ranges, cap, blocked_dates=frozenset()):
    """The single longest continuous absence the caller can still book in
    [today, year_end], or None if nothing is bookable."""
    best = top_breaks(
        today, year_end, balance, holidays, existing_ranges, cap, limit=1, blocked_dates=blocked_dates
    )
    return best[0] if best else None


# --- Group-break finder (the optimizer's second job) -------------------------

# One person in a group-break search: their remaining vacation `balance`, their
# consecutive `cap`, their `existing_ranges` of full-day leave, and `blocked_dates`
# they may not be off on (e.g. an existing half-day — present, so it also bounds a
# run). Holidays are company-wide and passed separately.
Member = namedtuple("Member", "balance cap existing_ranges blocked_dates", defaults=(frozenset(),))


def _member_can_be_off(member, w_start, w_end, holidays):
    """Whether `member` can be off for the whole window [w_start, w_end]: the window
    covers none of their blocked dates, the new vacation days it costs them fit their
    balance, and the continuous absence it forms (window + their adjacent
    leave/weekends/holidays) stays within their cap."""
    if any(w_start <= d <= w_end for d in member.blocked_dates):
        return False
    cost = 0
    d = w_start
    while d <= w_end:
        if is_worked(d, holidays, member.existing_ranges):
            cost += 1
        d += _ONE
    if cost > member.balance:
        return False

    _, _, run = continuous_absence(w_start, w_end, holidays, member.existing_ranges)
    return run <= _as_cap(member.cap)


def _has_working_day(w_start, w_end, holidays):
    d = w_start
    while d <= w_end:
        if is_worked(d, holidays):
            return True
        d += _ONE
    return False


def group_break(today, year_end, holidays, members):
    """The longest single window in [today, year_end] every member can be off at
    once (vacation-only, each within their own balance, cap and existing
    bookings), or None if no such shared break exists. Returns just the (start,
    end) window — never any individual's balance or which member was the binding
    constraint. The window must contain a real working day (a pure weekend isn't a
    break); ties on length resolve to the earliest window."""
    if not members:
        return None
    max_len = min(min(_as_cap(m.cap) for m in members), (year_end - today).days + 1)
    for length in range(max_len, 0, -1):
        w_start = today
        last_start = year_end - timedelta(days=length - 1)
        while w_start <= last_start:
            w_end = w_start + timedelta(days=length - 1)
            if _has_working_day(w_start, w_end, holidays) and all(
                _member_can_be_off(m, w_start, w_end, holidays) for m in members
            ):
                return (w_start, w_end)
            w_start += _ONE
    return None
