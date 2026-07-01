"""Leave-year calendar seam: the single home for where the current leave period
starts and ends, and when it next resets. Pure — no DB, no clock, no side effects.

The leave year is a company-wide, configurable, forward-only boundary. It recurs
on a `(month, day)` — 1 Jan by default, so the period is exactly the calendar year
and behavior is identical to before. Everything balance-adjacent that used to assume
`today.year` / `date(today.year, 1, 1)` / `date(today.year, 12, 31)` reads its
window from here instead.
"""

from calendar import isleap
from datetime import date


def reset_date(year, month, day):
    """The `(month, day)` reset date in `year`. A 29 Feb reset clamps to 28 Feb in a
    common year, so it still lands exactly once a year."""
    if month == 2 and day == 29 and not isleap(year):
        day = 28
    return date(year, month, day)


def next_reset(today, month, day):
    """The earliest occurrence of `(month, day)` strictly after `today` — the day
    the current leave period ends and the next one begins."""
    occ = reset_date(today.year, month, day)
    if occ <= today:
        occ = reset_date(today.year + 1, month, day)
    return occ


def last_reset(today, month, day):
    """The latest occurrence of `(month, day)` on or before `today` — the day the
    current leave period began."""
    occ = reset_date(today.year, month, day)
    if occ > today:
        occ = reset_date(today.year - 1, month, day)
    return occ


def leave_period(today, month, day):
    """The `(start, end)` leave period containing `today`: `[last reset, next reset)`,
    `end` exclusive. For the 1-Jan default this is exactly `[1 Jan, 1 Jan next year)`
    — the calendar year. Always has positive length (start <= today < end)."""
    return last_reset(today, month, day), next_reset(today, month, day)


def current_period(today, month, day, anchor=None, period_start=None):
    """The `(start, end)` leave period containing `today`, honouring a stored
    forward-only pin.

    With no `anchor`, the plain recurrence around today (`leave_period`) — the
    calendar year for 1 Jan. With a stored `anchor` (the pinned next reset) and its
    `period_start`, the current period keeps that pinned `[start, anchor)` until
    `today` reaches the anchor, then advances a year at a time aligned to
    `(month, day)`. This is how a reset date changed mid-period stays forward-only:
    the one-time stub/stretch period holds its original start, and every period after
    the anchor is the regular recurrence."""
    if anchor is None:
        return leave_period(today, month, day)
    start, end = period_start, anchor
    while today >= end:
        start, end = end, next_reset(end, month, day)
    return start, end


def reset_transition(today, current_end, new_month, new_day):
    """Compute the forward-only move to a new reset `(month, day)`.

    Returns `(new_end, kind)` where `new_end` is the earliest occurrence of the new
    `(month, day)` strictly after `today` and `kind` is:
      - ``"stub"`` when the new reset lands before the current period end (the
        current period is shortened),
      - ``"stretch"`` when it lands after (the current period is lengthened),
      - ``"unchanged"`` when it matches the current end.

    Forward-only: the current period keeps its original start, so no past period is
    reclassified. This is the home for the transition logic the carry-over modal
    (choosing the reset date) drives."""
    new_end = next_reset(today, new_month, new_day)
    if new_end < current_end:
        kind = "stub"
    elif new_end > current_end:
        kind = "stretch"
    else:
        kind = "unchanged"
    return new_end, kind


def period_key(start):
    """The stable key for the leave period beginning on `start`, used to store
    carry-in uniquely per period. A period that starts on 1 Jan keys to the year
    string (``"2026"``) — byte-compatible with existing stored `carry_in` keys, so an
    untouched system needs no migration; any other start keys to its ISO date. Keyed
    by the start alone (not the current reset month/day), so a reset date changed
    forward-only keeps the current period's existing key — its stored carry-in, and
    thus the balance, doesn't shift — while two resets in one calendar year (a stub:
    1 Jan then 13 Apr 2026) still key distinctly."""
    if (start.month, start.day) == (1, 1):
        return str(start.year)
    return start.isoformat()
