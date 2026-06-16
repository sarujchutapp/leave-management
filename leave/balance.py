"""Weekday counting. Quota is consumed by weekdays (Mon-Fri) only; weekends
are free. Public holidays are not modelled (documented v1 limitation)."""

from datetime import timedelta


def count_weekdays(start, end):
    """Number of Mon-Fri days in the inclusive range. 0 if end is before start."""
    if end < start:
        return 0
    days = 0
    current = start
    while current <= end:
        if current.weekday() < 5:  # 0=Mon .. 4=Fri
            days += 1
        current += timedelta(days=1)
    return days


def request_days(start, end, half=None):
    """Quota a request consumes. A half-day (`half` set, always a single date)
    costs 0.5 of a working weekday and nothing on a non-working day; otherwise
    it's the weekday count of the range."""
    if half:
        return 0.5 if count_weekdays(start, end) == 1 else 0
    return count_weekdays(start, end)
