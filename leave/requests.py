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
from botocore.exceptions import ClientError

from leave.absence import continuous_absence
from leave.balance import request_days
from leave.board import reset_board
from leave.carryover import roll_forward
from leave.db import iter_employees
from leave.holidays import holidays_between
from leave.leave_year import current_period, next_reset, period_key, reset_date
from leave.policy import allowance_for, get_policy

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


def _current_period(policy, today):
    """The current leave period `(start, end)` (`end` exclusive) from the central reset
    date, honouring a stored forward-only pin (`reset_anchor` / `reset_period_start`)."""
    return current_period(
        today,
        policy["reset_month"],
        policy["reset_day"],
        policy.get("reset_anchor"),
        policy.get("reset_period_start"),
    )


def _period_bounds(db, today, policy=None):
    """The current leave period `[start, last_day]` (both inclusive `date`s) from the
    central reset date, for querying the `by_employee` GSI. `last_day` is the day
    before the next reset, so the reset day itself opens the next period."""
    policy = policy or get_policy(db)
    start, end = _current_period(policy, today)
    return start, end - timedelta(days=1)


def _approved_weekdays_in(db, employee_id, leave_type, start, last_day):
    """Sum of weekdays across this employee's approved requests of `leave_type` whose
    start_date falls in the inclusive `[start, last_day]` window. Holidays are read
    across that window (which may span two calendar years)."""
    resp = db.requests.query(
        IndexName=db.by_employee_index,
        KeyConditionExpression=Key("employee_id").eq(employee_id)
        & Key("start_date").between(start.isoformat(), last_day.isoformat()),
    )
    holidays = holidays_between(db, start, last_day)
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


def approved_weekdays_this_year(db, employee_id, leave_type, today):
    """Sum of weekdays across this employee's approved requests of this type whose
    start_date falls in the current leave period (the calendar year by default)."""
    start, last_day = _period_bounds(db, today)
    return _approved_weekdays_in(db, employee_id, leave_type, start, last_day)


def _persist_carry_in(db, employee, cmap):
    """Write the employee's whole carry_in map and mirror it onto the in-memory
    employee dict so later reads in the same request see it."""
    db.employees.update_item(
        Key={"slack_user_id": employee["slack_user_id"]},
        UpdateExpression="SET carry_in = :c",
        ExpressionAttributeValues={":c": cmap},
    )
    employee["carry_in"] = cmap


def _stored_start(key):
    """The period start a stored carry_in key names. A bare 4-digit year key is a
    1-Jan start (byte-compatible with pre-reset-date data); anything else is an ISO
    start date."""
    if len(key) == 4 and key.isdigit():
        return date(int(key), 1, 1)
    return date.fromisoformat(key)


def _next_period_start(s, month, day, anchor, period_start):
    """Where the period beginning on `s` ends and the next begins. Normally the next
    reset after `s`; for the one-time pinned stub/stretch period (`s` is the pinned
    `period_start`) it is the stored `anchor`, so the roll-forward treats that
    irregular period as a single unit rather than splitting it on the recurrence."""
    if period_start is not None and s == period_start:
        return anchor
    return next_reset(s, month, day)


def carry_in_for(db, employee, today, policy=None):
    """Vacation days carried into the leave period containing `today` for this
    employee — the one persisted balance figure. Computed lazily and rolled forward,
    period by period, from the latest stored one; an employee with no stored carry
    yet is treated as starting this period (carry_in = 0), so a new hire never
    accrues carry for periods they didn't work. Keyed per reset period (by start
    date), and deterministic, so recomputing never double-counts. The advance fires
    whenever `today` has moved into a period not yet stored — not on a fixed calendar
    year — and a forward-only reset-date change keeps the current period's key, so its
    stored carry (and the balance) doesn't shift."""
    policy = policy or get_policy(db)
    month, day = policy["reset_month"], policy["reset_day"]
    anchor, period_start = policy.get("reset_anchor"), policy.get("reset_period_start")
    base = allowance_for(policy, employee, "vacation")
    max_carry = policy["max_carry_over"]["vacation"]
    max_total = policy["max_total"]["vacation"]

    cur_start, _ = _current_period(policy, today)
    cur_key = period_key(cur_start)

    cmap = {k: int(v) for k, v in (employee.get("carry_in") or {}).items()}
    if cur_key in cmap:
        return cmap[cur_key]

    if not cmap:
        cmap[cur_key] = 0  # first period ever seen — start of accrual
    else:
        s = max(_stored_start(k) for k in cmap)
        start_carry = cmap[period_key(s)]
        # Period boundaries are pure date math; the vacation used in each is one
        # query each. Gather both, then roll the carry forward in one pure step.
        ends, used = [], []
        while s < cur_start:
            p_end = _next_period_start(s, month, day, anchor, period_start)  # this period's exclusive end
            ends.append(p_end)
            used.append(
                _approved_weekdays_in(
                    db, employee["slack_user_id"], "vacation", s, p_end - timedelta(days=1)
                )
            )
            s = p_end
        rolled = roll_forward(base, max_carry, max_total, start_carry, used)
        for p_end, ci in zip(ends, rolled):
            cmap[period_key(p_end)] = ci
        cmap.setdefault(cur_key, 0)

    _persist_carry_in(db, employee, cmap)
    return cmap[cur_key]


def recompute_carry_in(db, employee, year):
    """Rebuild the `year` reset period's carry_in (and any later stored ones) from the
    stored chain — the operator escape hatch after a closed prior period is edited."""
    policy = get_policy(db)
    month, day = policy["reset_month"], policy["reset_day"]
    # A date in the `year` period, honouring a forward-only pin (whose period may start
    # off the recurrence), so the rebuild lands on the right period key.
    pin_start = policy["reset_period_start"]
    rebuild_day = pin_start if (pin_start and pin_start.year == year) else reset_date(year, month, day)
    cmap = {k: int(v) for k, v in (employee.get("carry_in") or {}).items()}
    cmap = {k: v for k, v in cmap.items() if _stored_start(k).year < year}
    _persist_carry_in(db, employee, cmap)
    return carry_in_for(db, employee, rebuild_day, policy)


def recompute_all_carry_in(db, year):
    """Rebuild every employee's stored `year` carry_in from their stored chain under
    the current policy caps — run after the carry-over caps change so persisted
    carry_in (which `max_carry_over` feeds) isn't left stale. Iterates the whole
    employees table; the reserved policy/board items are skipped. Returns the
    number of employees recomputed."""
    count = 0
    for item in iter_employees(db):
        recompute_carry_in(db, item, year)
        count += 1
    return count


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
        carry = carry_in_for(db, employee, today, policy)
        available = _vacation_available(base, carry, policy["max_total"]["vacation"])
        return available - used
    return base - used


def approved_weekdays_by_type_this_year(db, employee_id, today):
    """Approved weekdays per leave type for the current leave period (the calendar
    year by default), from a single `by_employee` query. Lets callers that need every
    type (the /dayoff modal) avoid one query per type."""
    start, last_day = _period_bounds(db, today)
    resp = db.requests.query(
        IndexName=db.by_employee_index,
        KeyConditionExpression=Key("employee_id").eq(employee_id)
        & Key("start_date").between(start.isoformat(), last_day.isoformat()),
    )
    holidays = holidays_between(db, start, last_day)
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
            carry = carry_in_for(db, employee, today, policy)
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
    the current leave period (the calendar year by default; half-days count 0.5).
    Subtracted from the approved-only remaining balance to get free-to-book days:
    pending is treated as reserved, so a request can't be filed against quota already
    spoken for, and approving any subset can never overshoot (see ADR-0010, superseding
    ADR-0008). The optimizer uses the same free notion so its suggestions match what
    the validator will accept."""
    start, last_day = _period_bounds(db, today)
    resp = db.requests.query(
        IndexName=db.by_employee_index,
        KeyConditionExpression=Key("employee_id").eq(employee_id)
        & Key("start_date").between(start.isoformat(), last_day.isoformat()),
    )
    holidays = holidays_between(db, start, last_day)
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
    leave) bounds it. The window for holidays comfortably exceeds any cap."""
    ranges = active_full_leave_ranges(db, employee_id)
    holidays = holidays_between(db, start - timedelta(days=60), end + timedelta(days=60))
    _, _, days = continuous_absence(start, end, holidays, ranges)
    return days


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


def _won_transition(update):
    """Run a conditional status update, returning True if it applied and False if the
    condition failed (another writer already moved the request). Makes the pending->
    decided transitions atomic, so a double-click or duplicate delivery can't fire the
    side effects (calendar event, DMs, board) twice."""
    try:
        update()
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def approve_request(db, request_id):
    """Move a request pending -> approved. Returns True if this call performed the
    transition, False if it was already decided (the caller must then skip the
    approval side effects)."""
    return _won_transition(
        lambda: db.requests.update_item(
            Key={"request_id": request_id},
            UpdateExpression="SET #s = :s, updated_at = :u",
            ConditionExpression="#s = :pending",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "approved", ":u": _now_iso(), ":pending": "pending"},
        )
    )


def decline_request(db, request_id, reason):
    """Move a request pending -> declined. Returns True if this call performed the
    transition, False if it was already decided."""
    return _won_transition(
        lambda: db.requests.update_item(
            Key={"request_id": request_id},
            UpdateExpression="SET #s = :s, decline_reason = :r, updated_at = :u",
            ConditionExpression="#s = :pending",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "declined", ":r": reason, ":u": _now_iso(), ":pending": "pending"
            },
        )
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
    """The employee's requests the cancel flow can act on: any pending one, an approved
    one that hasn't started yet (a full cancel), or an in-progress one that can still
    be returned early (full-day with working days left to give back). Ordered by start
    date."""
    requests = [_deserialize(r) for r in _by_employee(db, employee_id)]
    cancellable = [
        r
        for r in requests
        if r["status"] == "pending"
        or (r["status"] == "approved" and r["start_date"] > today)
        or is_early_returnable(db, r, today)
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


def is_early_returnable(db, request, today):
    """Whether an in-progress leave can be returned early: it's a full-day leave with
    working days left after today to give back. A half-day (always a single date) is
    never an early return, and a leave that ends today or whose remaining days are all
    weekend/holiday has nothing to return."""
    return (
        is_in_progress(request, today)
        and not request.get("half")
        and early_return_reclaim_days(db, request, today) > 0
    )


def early_return(db, request_id, today):
    """Shorten an in-progress leave to end today. It stays approved: days through
    today remain consumed, and the tail refunds automatically through the derived
    balance (no stored-balance write, no carry-in recompute).

    Guarded like the other transitions: applies only while the request is still an
    approved leave that extends past today, so a racing cancel or a double-submit
    can't shorten it twice or double-fire its side effects. Returns True if it
    applied, False if the guard failed."""
    try:
        db.requests.update_item(
            Key={"request_id": request_id},
            UpdateExpression="SET end_date = :e, updated_at = :u",
            ConditionExpression="#s = :approved AND end_date > :e",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":e": today.isoformat(),
                ":approved": "approved",
                ":u": _now_iso(),
            },
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def cancel_request(db, request_id):
    """Move a request pending/approved -> cancelled. Returns True if this call performed
    the transition, False if it was already cancelled/declined (so the caller skips the
    withdraw/calendar/board side effects). `can_cancel` still gates the business rule
    (an approved request must not have started); this guards the concurrent double-fire."""
    return _won_transition(
        lambda: db.requests.update_item(
            Key={"request_id": request_id},
            UpdateExpression="SET #s = :s, updated_at = :u",
            ConditionExpression="#s IN (:pending, :approved)",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "cancelled", ":u": _now_iso(), ":pending": "pending", ":approved": "approved"
            },
        )
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
    for item in iter_employees(db):
        if "carry_in" in item:
            db.employees.update_item(
                Key={"slack_user_id": item["slack_user_id"]},
                UpdateExpression="REMOVE carry_in",
            )


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
