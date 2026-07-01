"""Burnout measures — pure functions over plain inputs (no DB, no Slack).

The primary measure is the **no-break stretch**: how long a person goes without
time off, from their last *taken* leave to their next booked one. The supporting
flag is the **longest working stretch**: the longest run of working days no leave
interrupts. Both are explainable by construction — plain day arithmetic, no score.
"""

from datetime import date, timedelta


def no_break_stretch(today, last_taken_end, period_start=None):
    """Calendar days a person has actually gone without time off: from the end of
    their last taken (past approved) leave up to today. With no past leave the
    window opens at the start of the current leave period (`period_start`, or the
    calendar-year start when not given — a defined anchor, never an error). Looks
    *backward only* — a break booked ahead is relief, not time already endured, so
    it never inflates this count (it lowers risk instead; see the board's ranking)."""
    anchor = last_taken_end or period_start or date(today.year, 1, 1)
    return max((today - anchor).days, 0)


def expiring_quota(remaining_vacation, max_carry_over):
    """Vacation days that won't survive the leave-year reset: the remaining balance
    beyond what the policy lets carry over (`max_carry_over`), floored at zero. A
    person holding no more than the cap loses nothing — the rest carries into the next
    period. Explainable by construction: plain subtraction against the live policy cap."""
    return max(remaining_vacation - max_carry_over, 0)


def longest_working_stretch(start, end, leave_ranges, holidays):
    """The longest run of working days (Mon-Fri, holidays excluded) within
    [start, end] that no leave interrupts. Weekends and holidays span a run
    rather than break it (they aren't a real break from work); a day inside any
    leave range resets the run. Counted in working days, not calendar days."""
    run = best = 0
    d = start
    while d <= end:
        if any(s <= d <= e for s, e in leave_ranges):
            run = 0
        elif d.weekday() < 5 and d not in holidays:
            run += 1
            best = max(best, run)
        d += timedelta(days=1)
    return best
