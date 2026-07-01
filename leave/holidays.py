"""Company holidays — a single shared, admin-maintained set, stored as one
reserved `__holidays__` item in the employees table (like `__policy__` /
`__board__`).

Holidays are company-wide config read on nearly every request, not a per-entity
collection, so a keyed singleton fits: one GetItem serves every year and no
separate table (or extra `dynamodb:CreateTable` IAM) is needed. See ADR-0001.

Stored shape: `{ "<iso date>": {"label": str, "calendar_event_id": str|None} }`.
A `date` goes in / comes out; ISO strings stay inside this module. Writes are a
read-modify-write of the one item — fine, since holidays change rarely (initial
setup plus the odd admin edit) and a single admin maintains them.
"""

from datetime import date

HOLIDAYS_KEY = "__holidays__"


def _load(db):
    """The whole holidays map (iso date -> {label, calendar_event_id}), or {} when
    none are set yet (no reserved item) — so the system simply runs holiday-free."""
    item = db.employees.get_item(Key={"slack_user_id": HOLIDAYS_KEY}).get("Item")
    return (item or {}).get("holidays", {})


def _save(db, holidays):
    """Write the whole holidays map back. UpdateItem upserts the reserved item."""
    db.employees.update_item(
        Key={"slack_user_id": HOLIDAYS_KEY},
        UpdateExpression="SET holidays = :h",
        ExpressionAttributeValues={":h": holidays},
    )


def upsert_holiday(db, holiday_date, label, calendar_event_id=None):
    """Add or update one holiday. Idempotent by date; `calendar_event_id` is the
    slot the calendar-mirror fills."""
    holidays = _load(db)
    holidays[holiday_date.isoformat()] = {"label": label, "calendar_event_id": calendar_event_id}
    _save(db, holidays)


def delete_holiday(db, holiday_date):
    """Remove one holiday. Returns its stored entry (for calendar cleanup), or None
    if it wasn't set."""
    holidays = _load(db)
    removed = holidays.pop(holiday_date.isoformat(), None)
    if removed is not None:
        _save(db, holidays)
    return removed


def holidays_for_year(db, year):
    """The set of holiday `date`s in the given year, from one keyed read."""
    prefix = f"{year}-"
    return {date.fromisoformat(k) for k in _load(db) if k.startswith(prefix)}


def holidays_between(db, start, end):
    """The set of holiday `date`s within the inclusive range, from one keyed read."""
    out = set()
    for k in _load(db):
        d = date.fromisoformat(k)
        if start <= d <= end:
            out.add(d)
    return out


def get_holiday(db, holiday_date):
    """The stored entry ({label, calendar_event_id}) for a date, or None."""
    return _load(db).get(holiday_date.isoformat())


def all_holidays(db):
    """Every holiday as (date, label, calendar_event_id), earliest first — for the
    admin remove picker."""
    return [
        (date.fromisoformat(k), v.get("label"), v.get("calendar_event_id"))
        for k, v in sorted(_load(db).items())
    ]


def _title(label):
    return f"Holiday: {label}"


def apply_holidays(db, calendar, rows):
    """Upsert each (date, label) into the store and mirror it onto the team
    calendar as an all-day event. Idempotent: an existing holiday's event is
    updated in place (no duplicate). Add/update-only — dates absent from `rows`
    are left untouched. One read-modify-write of the holidays item for the batch."""
    holidays = _load(db)
    for holiday_date, label in rows:
        existing = holidays.get(holiday_date.isoformat())
        event_id = existing.get("calendar_event_id") if existing else None
        if event_id:
            calendar.update_event(event_id, _title(label))
        else:
            event_id = calendar.create_event(_title(label), holiday_date, holiday_date)
        holidays[holiday_date.isoformat()] = {"label": label, "calendar_event_id": event_id}
    _save(db, holidays)


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


def parse_holiday_text(raw):
    """Parse pasted `date,label` text into (date, label) pairs. Accepts comma- or
    tab-delimited rows (an Excel/Sheets copy yields tabs), splitting each line on the
    first delimiter only so a label keeps any commas it contains. Skips blank lines
    and a leading `date,label` header."""
    rows = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        delimiter = "\t" if "\t" in line else ","
        first, _, rest = line.partition(delimiter)
        first = first.strip()
        if first.lower() == "date":  # header
            continue
        rows.append((date.fromisoformat(first), rest.strip()))
    return rows
