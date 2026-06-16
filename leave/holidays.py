"""Company holidays store (DynamoDB) and the holiday-set queries day-counting uses.

Storage boundary: the only place that knows holidays live in DynamoDB. Holidays
are partitioned by `year` (sort key `holiday_date`, ISO `YYYY-MM-DD`) so a year's
holidays come back from a single Query — no table scan (consistent with ADR-0001).
A `date` goes in / comes out; ISO strings stay inside this module.
"""

from datetime import date

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

# When the holidays table isn't provisioned yet (no table, or the Lambda role lacks
# the read grant), treat the company as having no holidays rather than erroring — so
# the rest of the system runs. Reads auto-enable once the table + IAM exist.
_NOT_PROVISIONED = {"ResourceNotFoundException", "AccessDeniedException"}


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
    """The set of holiday `date`s in the given year, from one Query. Returns an
    empty set if the holidays table isn't provisioned yet (see _NOT_PROVISIONED)."""
    try:
        resp = db.holidays.query(KeyConditionExpression=Key("year").eq(str(year)))
    except ClientError as e:
        if e.response["Error"]["Code"] in _NOT_PROVISIONED:
            return set()
        raise
    return {date.fromisoformat(i["holiday_date"]) for i in resp["Items"]}


def holidays_between(db, start, end):
    """The set of holiday `date`s within the inclusive range, querying each year
    the range spans (usually one)."""
    out = set()
    for year in range(start.year, end.year + 1):
        out |= {d for d in holidays_for_year(db, year) if start <= d <= end}
    return out


def get_holiday(db, holiday_date):
    """The stored holiday item for a date, or None."""
    return db.holidays.get_item(
        Key={"year": str(holiday_date.year), "holiday_date": holiday_date.isoformat()}
    ).get("Item")


def _title(label):
    return f"Holiday: {label}"


def apply_holidays(db, calendar, rows):
    """Upsert each (date, label) into the store and mirror it onto the team
    calendar as an all-day event. Idempotent: an existing holiday's event is
    updated in place (no duplicate). Add/update-only — dates absent from `rows`
    are left untouched."""
    for holiday_date, label in rows:
        existing = get_holiday(db, holiday_date)
        event_id = existing.get("calendar_event_id") if existing else None
        if event_id:
            calendar.update_event(event_id, _title(label))
        else:
            event_id = calendar.create_event(_title(label), holiday_date, holiday_date)
        upsert_holiday(db, holiday_date, label, event_id)


def parse_holiday_rows(raw_rows):
    """Turn raw CSV rows (lists/tuples of strings) into (date, label) pairs.
    Skips blank rows and a leading `date,label` header."""
    rows = []
    for raw in raw_rows:
        if not raw or not raw[0].strip():
            continue
        first = raw[0].strip()
        if first.lower() == "date":  # header
            continue
        rows.append((date.fromisoformat(first), raw[1].strip()))
    return rows
