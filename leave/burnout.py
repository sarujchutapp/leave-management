"""Burnout measures — pure functions over plain inputs (no DB, no Slack).

The primary measure is the **no-break stretch**: how long a person goes without
time off, from their last *taken* leave to their next booked one. The supporting
flag is the **longest working stretch**: the longest run of working days no leave
interrupts. Both are explainable by construction — plain day arithmetic, no score.
"""

from datetime import date, timedelta


def no_break_stretch(today, last_taken_end, next_booked_start):
    """Calendar days of the no-leave window the person sits in: from the end of
    their last taken (past approved) leave to the start of their next booked
    (future approved/pending) leave. With no past leave the window opens at the
    start of the year (a defined anchor, never an error); with nothing booked
    ahead it runs to today (the dry spell so far)."""
    anchor = last_taken_end or date(today.year, 1, 1)
    end = next_booked_start or today
    return max((end - anchor).days, 0)


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
