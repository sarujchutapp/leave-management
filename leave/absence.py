"""Continuous-absence arithmetic — pure day math, no DB and no Slack.

A **continuous absence** (CONTEXT.md) is a maximal unbroken run of consecutive
calendar days an employee does not work. A **worked day** — a weekday that is
neither a holiday nor a day off — bounds the run on each side; weekends, holidays
and days off fill it.

The counter is deliberately dumb: callers pass the date ranges that count as days
off (their existing full-day leave, and for a suggestion the break being proposed).
It knows nothing about leave types, half-days, or bookings — a half-day is simply
left out of the off-ranges by the caller, so it reads as a worked day and bounds a
run, exactly as the domain says a 'present' day should.
"""

from datetime import timedelta

_ONE = timedelta(days=1)

# Safety backstop so the extension can't run away (e.g. a bug handing it an endless
# holiday set). No real continuous absence approaches this.
_GUARD = 400


def is_worked(d, holidays, off_ranges=()):
    """Whether `d` is a day actually worked: a weekday (Mon-Fri) that is neither a
    holiday nor inside any `off_range`. A worked day bounds a continuous absence;
    everything else (weekend, holiday, day off) fills it."""
    if d.weekday() >= 5 or d in holidays:
        return False
    return not any(s <= d <= e for s, e in off_ranges)


def continuous_absence(start, end, holidays, off_ranges=()):
    """The continuous absence the `[start, end]` span joins, as
    `(run_start, run_end, calendar_days)`. The span itself is off; outside it,
    weekends, holidays and any `off_range` fill the run until a worked day bounds
    it. `off_ranges` are the caller's *other* days off (existing full-day leave, or
    a proposed break) — never the `[start, end]` span, which is off by definition."""
    run_start, run_end, guard = start, end, 0
    while guard < _GUARD and not is_worked(run_start - _ONE, holidays, off_ranges):
        run_start -= _ONE
        guard += 1
    guard = 0
    while guard < _GUARD and not is_worked(run_end + _ONE, holidays, off_ranges):
        run_end += _ONE
        guard += 1
    return run_start, run_end, (run_end - run_start).days + 1
