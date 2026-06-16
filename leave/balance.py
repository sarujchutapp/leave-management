"""Weekday counting. Quota is consumed by weekdays (Mon-Fri) only; weekends
are free, and any date in the `holidays` set is skipped too."""

from datetime import timedelta


def count_weekdays(start, end, holidays=()):
    """Number of Mon-Fri days in the inclusive range, excluding any date in
    `holidays`. 0 if end is before start."""
    if end < start:
        return 0
    days = 0
    current = start
    while current <= end:
        if current.weekday() < 5 and current not in holidays:  # 0=Mon .. 4=Fri
            days += 1
        current += timedelta(days=1)
    return days


def request_days(start, end, half=None, holidays=()):
    """Quota a request consumes. A half-day (`half` set, always a single date)
    costs 0.5 of a working weekday and nothing on a non-working day; otherwise
    it's the weekday count of the range. A holiday counts as a non-working day,
    so a half on a holiday costs 0 (holiday beats half)."""
    if half:
        return 0.5 if count_weekdays(start, end, holidays) == 1 else 0
    return count_weekdays(start, end, holidays)
