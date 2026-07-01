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


def period_key(start, month, day):
    """The stable key for the leave period beginning on `start`, used to store
    carry-in uniquely per period. For the 1-Jan default it is the year string
    (``"2026"``) — byte-compatible with existing stored `carry_in` keys, so an
    untouched system needs no migration. For any other reset date it is the start
    date's ISO string, which stays unique even when the one-time stub transition
    puts two resets in the same calendar year (e.g. 1 Jan then 13 Apr 2026)."""
    if (month, day) == (1, 1):
        return str(start.year)
    return start.isoformat()
