"""Leave request persistence (DynamoDB) and the derived-balance query.

Storage boundary: this module is the only place that knows requests live in
DynamoDB. Dates serialize to ISO `YYYY-MM-DD` strings on write (lexicographic
order matches chronological, so the `by_employee` GSI sort key is usable) and
back to `date` on read; `created_at`/`updated_at` are app-set ISO strings;
allowance values are coerced from `Decimal` to `int`. No `Decimal` and no ISO
date strings escape this module — callers receive `int` and `date`.
"""

import uuid
from datetime import date, datetime, timezone

from boto3.dynamodb.conditions import Key

from leave.balance import count_weekdays


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _deserialize(item):
    """Stored request item -> app types: ISO date strings back to `date`."""
    if item is None:
        return None
    item["start_date"] = date.fromisoformat(item["start_date"])
    item["end_date"] = date.fromisoformat(item["end_date"])
    return item


def _by_employee(db, employee_id):
    """All of one employee's request items, via the by_employee GSI."""
    resp = db.requests.query(
        IndexName=db.by_employee_index,
        KeyConditionExpression=Key("employee_id").eq(employee_id),
    )
    return resp["Items"]


def approved_weekdays_this_year(db, employee_id, leave_type, today):
    """Sum of weekdays across this employee's approved requests of this type
    whose start_date falls in the current calendar year."""
    year_start = date(today.year, 1, 1).isoformat()
    year_end = date(today.year, 12, 31).isoformat()
    resp = db.requests.query(
        IndexName=db.by_employee_index,
        KeyConditionExpression=Key("employee_id").eq(employee_id)
        & Key("start_date").between(year_start, year_end),
    )
    return sum(
        count_weekdays(date.fromisoformat(r["start_date"]), date.fromisoformat(r["end_date"]))
        for r in resp["Items"]
        if r["status"] == "approved" and r["leave_type"] == leave_type
    )


def remaining_balance(db, employee, leave_type, today):
    """Derived, never stored: allowance minus approved weekdays this year."""
    allowance = int(employee["allowances"][leave_type])
    used = approved_weekdays_this_year(db, employee["slack_user_id"], leave_type, today)
    return allowance - used


def has_overlap(db, employee_id, start, end):
    """True if the range overlaps any of the employee's pending/approved requests."""
    for r in _by_employee(db, employee_id):
        if r["status"] not in ("pending", "approved"):
            continue
        if date.fromisoformat(r["start_date"]) <= end and date.fromisoformat(r["end_date"]) >= start:
            return True
    return False


def create_request(db, employee_id, leave_type, start, end, reason):
    request_id = uuid.uuid4().hex
    now = _now_iso()
    db.requests.put_item(
        Item={
            "request_id": request_id,
            "employee_id": employee_id,
            "leave_type": leave_type,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "status": "pending",
            "reason": reason,
            "decline_reason": None,
            "calendar_event_id": None,
            "ticket_channel": None,
            "ticket_ts": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    return request_id


def get_request(db, request_id):
    item = db.requests.get_item(Key={"request_id": request_id}).get("Item")
    return _deserialize(item)


def approve_request(db, request_id):
    db.requests.update_item(
        Key={"request_id": request_id},
        UpdateExpression="SET #s = :s, updated_at = :u",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "approved", ":u": _now_iso()},
    )


def decline_request(db, request_id, reason):
    db.requests.update_item(
        Key={"request_id": request_id},
        UpdateExpression="SET #s = :s, decline_reason = :r, updated_at = :u",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "declined", ":r": reason, ":u": _now_iso()},
    )


def set_calendar_event_id(db, request_id, event_id):
    db.requests.update_item(
        Key={"request_id": request_id},
        UpdateExpression="SET calendar_event_id = :e",
        ExpressionAttributeValues={":e": event_id},
    )


def set_ticket_ref(db, request_id, channel, ts):
    db.requests.update_item(
        Key={"request_id": request_id},
        UpdateExpression="SET ticket_channel = :c, ticket_ts = :t",
        ExpressionAttributeValues={":c": channel, ":t": ts},
    )


def cancellable_requests(db, employee_id, today):
    """The employee's requests that can still be cancelled: any pending one, or
    an approved one that hasn't started yet. Ordered by start date."""
    requests = [_deserialize(r) for r in _by_employee(db, employee_id)]
    cancellable = [
        r
        for r in requests
        if r["status"] == "pending"
        or (r["status"] == "approved" and r["start_date"] > today)
    ]
    cancellable.sort(key=lambda r: r["start_date"])
    return cancellable


def can_cancel(request, today):
    if request["status"] == "pending":
        return True
    return request["status"] == "approved" and request["start_date"] > today


def cancel_request(db, request_id):
    db.requests.update_item(
        Key={"request_id": request_id},
        UpdateExpression="SET #s = :s, updated_at = :u",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "cancelled", ":u": _now_iso()},
    )
