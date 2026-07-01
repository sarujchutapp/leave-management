"""Leave request persistence (DynamoDB) and the derived-balance query.

Storage boundary: this module is the only place that knows requests live in
DynamoDB. Dates serialize to ISO `YYYY-MM-DD` strings on write (lexicographic
order matches chronological, so the `by_employee` GSI sort key is usable) and
back to `date` on read; `created_at`/`updated_at` are app-set ISO strings;
allowance values are coerced from `Decimal` to `int`. No `Decimal` and no ISO
date strings escape this module — callers receive `int` and `date`.
"""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key

from leave.balance import request_days
from leave.board import BOARD_KEY, reset_board
from leave.holidays import HOLIDAYS_KEY, holidays_between, holidays_for_year
from leave.policy import POLICY_KEY, allowance_for, get_policy

logger = logging.getLogger(__name__)


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
    holidays = holidays_for_year(db, today.year)
    return sum(
        request_days(
            date.fromisoformat(r["start_date"]),
            date.fromisoformat(r["end_date"]),
            r.get("half"),
            holidays,
        )
        for r in resp["Items"]
        if r["status"] == "approved" and r["leave_type"] == leave_type
    )


def _persist_carry_in(db, employee, cmap):
    """Write the employee's whole carry_in map and mirror it onto the in-memory
    employee dict so later reads in the same request see it."""
    db.employees.update_item(
        Key={"slack_user_id": employee["slack_user_id"]},
        UpdateExpression="SET carry_in = :c",
        ExpressionAttributeValues={":c": cmap},
    )
    employee["carry_in"] = cmap


def carry_in_for(db, employee, year, policy=None):
    """Vacation days carried into `year` for this employee — the one persisted
    balance figure. Computed lazily and rolled forward from the latest stored
    year; an employee with no stored carry yet is treated as starting this year
    (carry_in = 0), so a new hire never accrues carry for years they didn't work.
    Deterministic, so recomputing never double-counts."""
    cmap = {k: int(v) for k, v in (employee.get("carry_in") or {}).items()}
    if str(year) in cmap:
        return cmap[str(year)]

    policy = policy or get_policy(db)
    base = allowance_for(policy, employee, "vacation")
    max_carry = policy["max_carry_over"]["vacation"]
    max_total = policy["max_total"]["vacation"]

    if not cmap:
        cmap[str(year)] = 0  # first year ever seen — start of accrual
    else:
        last = max(int(y) for y in cmap)
        ci = cmap[str(last)]
        for y in range(last + 1, year + 1):
            available = min(base + ci, max_total)
            used = approved_weekdays_this_year(
                db, employee["slack_user_id"], "vacation", date(y - 1, 1, 1)
            )
            ci = min(max(available - used, 0), max_carry)
            cmap[str(y)] = ci
        cmap.setdefault(str(year), 0)

    _persist_carry_in(db, employee, cmap)
    return cmap[str(year)]


def recompute_carry_in(db, employee, year):
    """Rebuild carry_in[year] (and any later stored years) from the stored chain
    — the operator escape hatch after a closed prior year is edited."""
    cmap = {k: int(v) for k, v in (employee.get("carry_in") or {}).items()}
    cmap = {y: v for y, v in cmap.items() if int(y) < year}
    _persist_carry_in(db, employee, cmap)
    return carry_in_for(db, employee, year)


def recompute_all_carry_in(db, year):
    """Rebuild every employee's stored `year` carry_in from their stored chain under
    the current policy caps — run after the carry-over caps change so persisted
    carry_in (which `max_carry_over` feeds) isn't left stale. Iterates the whole
    employees table via Scan; the reserved policy/board items are skipped. Returns
    the number of employees recomputed."""
    count, scan_kwargs = 0, {}
    while True:
        resp = db.employees.scan(**scan_kwargs)
        for item in resp["Items"]:
            if item["slack_user_id"] in (POLICY_KEY, BOARD_KEY, HOLIDAYS_KEY):
                continue
            recompute_carry_in(db, item, year)
            count += 1
        if "LastEvaluatedKey" not in resp:
            return count
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _vacation_available(base, carry_in, max_total):
    """In-year vacation availability. `max_total` caps how much carry adds on top
    of the base grant; it never reduces the base itself (so an override above
    max_total keeps its full base)."""
    return base + max(0, min(carry_in, max_total - base))


def remaining_balance(db, employee, leave_type, today):
    """Derived: allowance minus approved weekdays this year. Vacation adds the
    capped carry-in; sick/personal just reset to base each year."""
    policy = get_policy(db)
    base = allowance_for(policy, employee, leave_type)
    used = approved_weekdays_this_year(db, employee["slack_user_id"], leave_type, today)
    if leave_type == "vacation":
        carry = carry_in_for(db, employee, today.year, policy)
        available = _vacation_available(base, carry, policy["max_total"]["vacation"])
        return available - used
    return base - used


def approved_weekdays_by_type_this_year(db, employee_id, today):
    """Approved weekdays per leave type for the current calendar year, from a single
    `by_employee` query. Lets callers that need every type (the /dayoff modal) avoid
    one query per type."""
    year_start = date(today.year, 1, 1).isoformat()
    year_end = date(today.year, 12, 31).isoformat()
    resp = db.requests.query(
        IndexName=db.by_employee_index,
        KeyConditionExpression=Key("employee_id").eq(employee_id)
        & Key("start_date").between(year_start, year_end),
    )
    holidays = holidays_for_year(db, today.year)
    totals = {}
    for r in resp["Items"]:
        if r["status"] != "approved":
            continue
        days = request_days(
            date.fromisoformat(r["start_date"]),
            date.fromisoformat(r["end_date"]),
            r.get("half"),
            holidays,
        )
        totals[r["leave_type"]] = totals.get(r["leave_type"], 0) + days
    return totals


def remaining_balances(db, employee, today):
    """All leave types' remaining balance, derived from a single year query (vs
    `remaining_balance` per type). Allowances come from the central policy, with the
    employee's override applied per type where present. Vacation adds capped carry-in."""
    policy = get_policy(db)
    used = approved_weekdays_by_type_this_year(db, employee["slack_user_id"], today)
    result = {}
    for t in policy["allowances"]:
        base = allowance_for(policy, employee, t)
        if t == "vacation":
            carry = carry_in_for(db, employee, today.year, policy)
            available = _vacation_available(base, carry, policy["max_total"]["vacation"])
        else:
            available = base
        result[t] = available - used.get(t, 0)
    return result


def active_full_leave_ranges(db, employee_id):
    """(start, end) for the employee's pending/approved FULL-day leave. Half-days
    are 'present' days, so they bound a continuous absence rather than fill it."""
    return [
        (date.fromisoformat(r["start_date"]), date.fromisoformat(r["end_date"]))
        for r in _by_employee(db, employee_id)
        if r["status"] in ("pending", "approved") and not r.get("half")
    ]


def pending_days(db, employee_id, leave_type, today):
    """Days of the employee's PENDING leave of `leave_type` whose start_date falls in
    the current year (half-days count 0.5). Subtracted from the approved-only remaining
    balance to get free-to-book days: pending is treated as reserved, so a request
    can't be filed against quota already spoken for, and approving any subset can never
    overshoot (see ADR-0010, superseding ADR-0008). The optimizer uses the same free
    notion so its suggestions match what the validator will accept."""
    year_start = date(today.year, 1, 1).isoformat()
    year_end = date(today.year, 12, 31).isoformat()
    resp = db.requests.query(
        IndexName=db.by_employee_index,
        KeyConditionExpression=Key("employee_id").eq(employee_id)
        & Key("start_date").between(year_start, year_end),
    )
    holidays = holidays_for_year(db, today.year)
    return sum(
        request_days(
            date.fromisoformat(r["start_date"]),
            date.fromisoformat(r["end_date"]),
            r.get("half"),
            holidays,
        )
        for r in resp["Items"]
        if r["status"] == "pending" and r["leave_type"] == leave_type
    )


def half_day_dates(db, employee_id):
    """The dates of the employee's pending/approved HALF-day leave. A half-day is a
    single date (start == end) and a 'present' day, so it can't be re-booked but
    still bounds a run — the optimizer treats these as blocked-but-present."""
    return {
        date.fromisoformat(r["start_date"])
        for r in _by_employee(db, employee_id)
        if r["status"] in ("pending", "approved") and r.get("half")
    }


def pending_approved_intervals(db, employee_id):
    """(start, end, status) for the employee's pending/approved leave, full or
    half day. Coverage Radar uses these to find peer overlaps (a half-day still
    reduces coverage, so it counts)."""
    return [
        (date.fromisoformat(r["start_date"]), date.fromisoformat(r["end_date"]), r["status"])
        for r in _by_employee(db, employee_id)
        if r["status"] in ("pending", "approved")
    ]


def continuous_absence_length(db, employee_id, start, end):
    """Calendar-day length of the unbroken non-working run a [start,end] full-day
    leave would join. Weekends, holidays, and the employee's existing full-day
    leave fill the run; a worked day (a weekday that is neither holiday nor full-day
    leave) bounds it. The window for holidays/extension comfortably exceeds any cap."""
    ranges = active_full_leave_ranges(db, employee_id)
    holidays = holidays_between(db, start - timedelta(days=60), end + timedelta(days=60))

    def non_working(d):
        if d.weekday() >= 5 or d in holidays or start <= d <= end:
            return True
        return any(s <= d <= e for s, e in ranges)

    run_start, run_end, guard = start, end, 0
    while guard < 400 and non_working(run_start - timedelta(days=1)):
        run_start -= timedelta(days=1)
        guard += 1
    guard = 0
    while guard < 400 and non_working(run_end + timedelta(days=1)):
        run_end += timedelta(days=1)
        guard += 1
    return (run_end - run_start).days + 1


def has_overlap(db, employee_id, start, end):
    """True if the range overlaps any of the employee's pending/approved requests."""
    for r in _by_employee(db, employee_id):
        if r["status"] not in ("pending", "approved"):
            continue
        if date.fromisoformat(r["start_date"]) <= end and date.fromisoformat(r["end_date"]) >= start:
            return True
    return False


def create_request(db, employee_id, leave_type, start, end, reason, half=None):
    request_id = uuid.uuid4().hex
    now = _now_iso()
    db.requests.put_item(
        Item={
            "request_id": request_id,
            "employee_id": employee_id,
            "leave_type": leave_type,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "half": half,
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
    """The employee's requests the cancel flow can act on: any pending one, or an
    approved one that hasn't ended yet — future (a full cancel) or in progress (an
    early return). Ordered by start date."""
    requests = [_deserialize(r) for r in _by_employee(db, employee_id)]
    cancellable = [
        r
        for r in requests
        if r["status"] == "pending"
        or (r["status"] == "approved" and r["end_date"] >= today)
    ]
    cancellable.sort(key=lambda r: r["start_date"])
    return cancellable


def can_cancel(request, today):
    """Actionable in the cancel flow: pending, or an approved leave not yet ended
    (future → full cancel, in progress → early return)."""
    if request["status"] == "pending":
        return True
    return request["status"] == "approved" and request["end_date"] >= today


def is_in_progress(request, today):
    """An approved leave currently underway (start ≤ today ≤ end). Cancelling one is
    an early return — it's shortened to end today rather than fully cancelled."""
    return (
        request["status"] == "approved"
        and request["start_date"] <= today <= request["end_date"]
    )


def early_return_reclaim_days(db, request, today):
    """Working days after today that an early return gives back — the tail
    (today, end]. Zero when the leave already ends today or the remaining days are
    all weekend/holiday."""
    tail_start = today + timedelta(days=1)
    if tail_start > request["end_date"]:
        return 0
    holidays = holidays_between(db, tail_start, request["end_date"])
    return request_days(tail_start, request["end_date"], None, holidays)


def early_return(db, request_id, today):
    """Shorten an in-progress leave to end today. It stays approved: days through
    today remain consumed, and the tail refunds automatically through the derived
    balance (no stored-balance write, no carry-in recompute)."""
    db.requests.update_item(
        Key={"request_id": request_id},
        UpdateExpression="SET end_date = :e, updated_at = :u",
        ExpressionAttributeValues={":e": today.isoformat(), ":u": _now_iso()},
    )


def cancel_request(db, request_id):
    db.requests.update_item(
        Key={"request_id": request_id},
        UpdateExpression="SET #s = :s, updated_at = :u",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "cancelled", ":u": _now_iso()},
    )


def _scan_all_requests(db):
    items, scan_kwargs = [], {}
    while True:
        resp = db.requests.scan(**scan_kwargs)
        items += resp["Items"]
        if "LastEvaluatedKey" not in resp:
            return items
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _wipe_all_carry_in(db):
    """Strip stored carry_in from every employee — part of Clear's clean slate, so
    no per-person carried-over days survive (ADR-0009). Skips the reserved items."""
    scan_kwargs = {}
    while True:
        resp = db.employees.scan(**scan_kwargs)
        for item in resp["Items"]:
            if item["slack_user_id"] in (POLICY_KEY, BOARD_KEY, HOLIDAYS_KEY):
                continue
            if "carry_in" in item:
                db.employees.update_item(
                    Key={"slack_user_id": item["slack_user_id"]},
                    UpdateExpression="REMOVE carry_in",
                )
        if "LastEvaluatedKey" not in resp:
            return
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def clear_all_requests(db, calendar, sheets, today, client=None):
    """Clean slate: delete every leave request and the artifacts it created — each
    approved request's calendar event, the request rows themselves, the saved board,
    and every employee's stored carry_in. When a Slack `client` is given, also
    withdraw each pending request's manager ticket so no orphan Approve/Decline
    buttons remain (the operator script passes none — it has no Slack context, and a
    stale click is handled gracefully by the approve/decline guards). Employees, the
    central-policy item, and holidays are kept. Shared by /control Clear and
    clear_requests.py. Returns the number of request rows deleted.

    Order matters: the database wipe + board reset + carry_in wipe (the source of
    truth) run FIRST, then the external cleanup. Calendar deletes and ticket
    withdrawals are slow, best-effort HTTP calls (a thing already gone must not
    matter); doing them last means a slow or timing-out API can never strand the
    database half-cleared — which on Lambda would leave the rows behind."""
    items = _scan_all_requests(db)
    with db.requests.batch_writer() as bw:
        for it in items:
            bw.delete_item(Key={"request_id": it["request_id"]})
    reset_board(db, sheets, today)
    _wipe_all_carry_in(db)
    for it in items:
        event_id = it.get("calendar_event_id")
        if event_id:
            try:
                calendar.delete_event(event_id)
            except Exception:
                logger.exception("calendar event %s delete failed during clear", event_id)
    if client is not None:
        for it in items:
            if it.get("status") == "pending" and it.get("ticket_ts"):
                try:
                    client.chat_update(
                        channel=it["ticket_channel"],
                        ts=it["ticket_ts"],
                        text="Request withdrawn",
                        blocks=[
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": "This request was withdrawn — all leave was cleared.",
                                },
                            }
                        ],
                    )
                except Exception:
                    logger.exception("ticket withdraw failed during clear for %s", it["request_id"])
    return len(items)
