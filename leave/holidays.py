"""Company holidays store (DynamoDB) and the holiday-set queries day-counting uses.

Storage boundary: the only place that knows holidays live in DynamoDB. Holidays
are partitioned by `year` (sort key `holiday_date`, ISO `YYYY-MM-DD`) so a year's
holidays come back from a single Query — no table scan (consistent with ADR-0001).
A `date` goes in / comes out; ISO strings stay inside this module.
"""

from datetime import date

from boto3.dynamodb.conditions import Key


def upsert_holiday(db, holiday_date, label, calendar_event_id=None):
    """Add or update a holiday. Idempotent by date; `calendar_event_id` is the
    slot the calendar-mirror (a later slice) fills."""
    db.holidays.put_item(
        Item={
            "year": str(holiday_date.year),
            "holiday_date": holiday_date.isoformat(),
            "label": label,
            "calendar_event_id": calendar_event_id,
        }
    )


def holidays_for_year(db, year):
    """The set of holiday `date`s in the given year, from one Query."""
    resp = db.holidays.query(KeyConditionExpression=Key("year").eq(str(year)))
    return {date.fromisoformat(i["holiday_date"]) for i in resp["Items"]}


def holidays_between(db, start, end):
    """The set of holiday `date`s within the inclusive range, querying each year
    the range spans (usually one)."""
    out = set()
    for year in range(start.year, end.year + 1):
        out |= {d for d in holidays_for_year(db, year) if start <= d <= end}
    return out
