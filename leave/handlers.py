"""Slack handler logic, written as plain functions so tests can pass fakes.

app.py registers these on the Bolt app, supplying a real DB connection; Bolt
injects ack/body/view/client/logger by parameter name.
"""

import json
from datetime import date

from leave.blocks import (
    CLEAR_CONFIRM_WORD,
    build_cancel_modal,
    build_carry_over_modal,
    build_clear_modal,
    build_control_menu,
    build_decision_notice,
    build_decline_modal,
    build_leave_limits_modal,
    build_leave_modal,
    build_settings_view,
    build_ticket,
    format_period,
)
from leave.board import update_board
from leave.calendar_client import color_id_for
from leave.db import get_employee
from leave.policy import get_policy, set_policy
from leave.report import build_report_csv
from leave.requests import (
    approve_request,
    can_cancel,
    cancel_request,
    cancellable_requests,
    clear_all_requests,
    create_request,
    decline_request,
    get_request,
    recompute_all_carry_in,
    remaining_balance,
    remaining_balances,
    set_calendar_event_id,
    set_ticket_ref,
)
from leave.validation import validate_request

CONTACT_ADMIN = "You're not set up in the leave system yet — please contact your admin."
NOT_APPROVER = "You're not the approver for this request."
NOTHING_TO_CANCEL = "You have no requests to cancel."
CANNOT_CANCEL = "That request can no longer be cancelled."
NOT_ADMIN = "Sorry, /control is for admins only."


def is_admin(user_id, admin_ids):
    """True if the Slack user is in the injected admin allowlist. The allowlist is
    passed in (sourced from SLACK_ADMIN_IDS in app.py) so tests can set it directly.
    An empty allowlist admits no one."""
    return user_id in admin_ids


def open_control_menu(ack, body, client, admin_ids):
    """`/control`: admins get the menu modal; everyone else gets a non-actionable
    note. Fast (modal open only), so it runs synchronously in both run modes."""
    if not is_admin(body["user_id"], admin_ids):
        ack(NOT_ADMIN)
        return
    ack()
    client.views_open(trigger_id=body["trigger_id"], view=build_control_menu())


def open_view_settings(ack, body, client, db, admin_ids):
    """View Settings button: re-checks admin (defense in depth, since the gate must
    hold on every sub-action, not just at command time) and pushes a read-only view
    of the current central policy."""
    ack()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    client.views_push(trigger_id=body["trigger_id"], view=build_settings_view(get_policy(db)))


# Block_ids of the leave-limits modal, also the keys of the parsed values. The
# first three are per-type allowances; the last is the vacation consecutive limit.
_LIMIT_FIELDS = ("sick", "vacation", "personal", "consecutive_limit")


def open_leave_limits(ack, body, client, db, admin_ids):
    """Leave limits button: re-checks admin, then pushes the modal pre-filled from
    the current central policy."""
    ack()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    client.views_push(trigger_id=body["trigger_id"], view=build_leave_limits_modal(get_policy(db)))


def _parse_int(raw):
    """(value, None) for a non-negative whole number, else (None, error)."""
    try:
        n = int(raw)
    except (ValueError, TypeError):
        return None, "Enter a whole number."
    if n < 0:
        return None, "Must be zero or greater."
    return n, None


def submit_leave_limits(ack, body, view, db, admin_ids):
    """Leave limits submit: re-check admin, validate every field, and on success
    write the new allowances + consecutive limit. Reads the current policy to keep
    the carry-over caps (set_policy overwrites the whole item) intact."""
    if not is_admin(body["user"]["id"], admin_ids):
        ack()
        return
    values = view["state"]["values"]
    parsed, errors = {}, {}
    for field in _LIMIT_FIELDS:
        n, err = _parse_int(values[field]["value"]["value"])
        if err:
            errors[field] = err
        else:
            parsed[field] = n
    if errors:
        ack(response_action="errors", errors=errors)
        return
    ack()
    policy = get_policy(db)
    set_policy(
        db,
        allowances={
            "sick": parsed["sick"],
            "vacation": parsed["vacation"],
            "personal": parsed["personal"],
        },
        max_carry_over=policy["max_carry_over"],
        max_total=policy["max_total"],
        consecutive_limit={"vacation": parsed["consecutive_limit"]},
    )


# Block_ids of the carry-over modal (also the keys of the parsed values).
_CARRY_FIELDS = ("max_carry_over", "max_total")


def open_carry_over(ack, body, client, db, admin_ids):
    """Carry-over button: re-checks admin, then pushes the modal pre-filled with the
    current vacation carry-over caps."""
    ack()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    client.views_push(trigger_id=body["trigger_id"], view=build_carry_over_modal(get_policy(db)))


def _parse_carry_over(view):
    """(parsed, errors) for the carry-over modal — non-negative whole numbers."""
    values = view["state"]["values"]
    parsed, errors = {}, {}
    for field in _CARRY_FIELDS:
        n, err = _parse_int(values[field]["value"]["value"])
        if err:
            errors[field] = err
        else:
            parsed[field] = n
    return parsed, errors


def submit_carry_over_ack(ack, body, view, db, admin_ids):
    """Ack phase (under 3s): re-check admin, validate, write the new caps. Returns
    True when applied, so the caller knows to run the post-ack recompute."""
    if not is_admin(body["user"]["id"], admin_ids):
        ack()
        return False
    parsed, errors = _parse_carry_over(view)
    if errors:
        ack(response_action="errors", errors=errors)
        return False
    ack()
    policy = get_policy(db)
    set_policy(
        db,
        allowances=policy["allowances"],
        max_carry_over={"vacation": parsed["max_carry_over"]},
        max_total={"vacation": parsed["max_total"]},
        consecutive_limit=policy["consecutive_limit"],
    )
    return True


def submit_carry_over_apply(body, view, db, admin_ids, today=None):
    """Post-ack work: rebuild every employee's stored carry_in under the new caps.
    Re-checks admin + validity because Lambda lazy listeners fire regardless of the
    ack result; an invalid/non-admin submission is dropped (no recompute)."""
    today = today or date.today()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    _, errors = _parse_carry_over(view)
    if errors:
        return
    recompute_all_carry_in(db, today.year)


def submit_carry_over(ack, body, view, db, admin_ids, today=None):
    """Synchronous submit (Socket Mode / tests): ack-with-validation, then recompute."""
    if submit_carry_over_ack(ack, body, view, db, admin_ids):
        submit_carry_over_apply(body, view, db, admin_ids, today)


def open_clear(ack, body, client, admin_ids):
    """Clear button: re-checks admin, then pushes the typed-confirm modal."""
    ack()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    client.views_push(trigger_id=body["trigger_id"], view=build_clear_modal())


def _clear_confirmed(view):
    raw = view["state"]["values"]["confirm"]["value"].get("value")
    return (raw or "").strip() == CLEAR_CONFIRM_WORD


def submit_clear_ack(ack, body, view, admin_ids):
    """Ack phase (under 3s): re-check admin and the typed confirmation word. Returns
    True only when an admin typed the word exactly, so the caller runs the wipe."""
    if not is_admin(body["user"]["id"], admin_ids):
        ack()
        return False
    if not _clear_confirmed(view):
        ack(
            response_action="errors",
            errors={"confirm": f"Type {CLEAR_CONFIRM_WORD} exactly to confirm."},
        )
        return False
    ack()
    return True


def submit_clear_apply(body, view, db, calendar, sheets, admin_ids, today=None):
    """Post-ack work: the actual wipe. Re-checks admin + confirmation because Lambda
    lazy listeners fire regardless of the ack result; an unconfirmed submission is
    dropped (nothing deleted)."""
    today = today or date.today()
    if not is_admin(body["user"]["id"], admin_ids) or not _clear_confirmed(view):
        return
    clear_all_requests(db, calendar, sheets, today)


def submit_clear(ack, body, view, db, calendar, sheets, admin_ids, today=None):
    """Synchronous submit (Socket Mode / tests): ack-with-confirmation, then wipe."""
    if submit_clear_ack(ack, body, view, admin_ids):
        submit_clear_apply(body, view, db, calendar, sheets, admin_ids, today)


def handle_report(ack, body, client, db, admin_ids, today=None):
    """Report button: re-checks admin, builds the all-employee CSV, and uploads it to
    the admin's DM (not a shared channel). The Scan + upload run post-ack — ack()
    here is a no-op in the lazy phase on Lambda, the real ack in Socket Mode."""
    ack()
    today = today or date.today()
    user_id = body["user"]["id"]
    if not is_admin(user_id, admin_ids):
        return
    csv_text = build_report_csv(db, today)
    dm = client.conversations_open(users=user_id)
    client.files_upload_v2(
        channel=dm["channel"]["id"],
        content=csv_text,
        filename="leave-report.csv",
        title="Leave usage report",
    )


def open_leave_modal(ack, body, client, db, today=None):
    today = today or date.today()
    employee = get_employee(db, body["user_id"])
    if employee is None:
        ack(CONTACT_ADMIN)
        return
    ack()
    balances = remaining_balances(db, employee, today)
    client.views_open(trigger_id=body["trigger_id"], view=build_leave_modal(balances))


def _to_gregorian(d):
    """Slack's date picker sends Buddhist-era years (CE + 543) in Thai locale.
    Convert those back to the Gregorian calendar."""
    if d.year >= 2400:
        return d.replace(year=d.year - 543)
    return d


def _parse_submission(view):
    values = view["state"]["values"]
    leave_type = values["leave_type"]["value"]["selected_option"]["value"]
    start = _to_gregorian(date.fromisoformat(values["start_date"]["value"]["selected_date"]))
    # End date is optional: blank means a single-day leave, so default it to start.
    end_raw = values.get("end_date", {}).get("value", {}).get("selected_date")
    end = _to_gregorian(date.fromisoformat(end_raw)) if end_raw else start
    reason = values["reason"]["value"].get("value")
    # Half-day selector defaults to "full"; "morning"/"afternoon" mark a half day.
    half_opt = values.get("half_day", {}).get("value", {}).get("selected_option") or {}
    half = half_opt.get("value")
    if half == "full":
        half = None
    return leave_type, start, end, reason, half


def _finalize_approval(db, calendar, request_id, employee, leave_type, start, end, half=None):
    """Mark approved and create the shared-calendar event, storing its id. The event
    is tinted with the employee's stable colour so the calendar is readable per person."""
    approve_request(db, request_id)
    summary = f"{employee['real_name']} — {leave_type}"
    if half:
        summary += f" ({half})"
    color_id = color_id_for(employee["slack_user_id"])
    event_id = calendar.create_event(summary, start, end, color_id)
    set_calendar_event_id(db, request_id, event_id)


def submit_leave_ack(ack, body, view, db, today=None):
    """Ack phase (must finish within Slack's 3s): validate and either return inline
    errors or a bare ack. Returns True when the submission is valid. The heavy work
    (calendar, board, manager DM) is done separately in submit_leave_apply so it can
    run post-ack — synchronously in Socket Mode, as a lazy listener on Lambda."""
    today = today or date.today()
    employee = get_employee(db, body["user"]["id"])
    leave_type, start, end, reason, half = _parse_submission(view)
    errors = validate_request(db, employee, leave_type, start, end, today, half)
    if errors:
        ack(response_action="errors", errors=errors)
        return False
    ack()
    return True


def submit_leave_apply(body, view, client, db, calendar, sheets=None, today=None):
    """Post-ack work: persist the request, then auto-approve (calendar + board) or DM
    the manager. Re-validates because Lambda lazy listeners fire regardless of the ack
    result; a now-invalid submission is simply dropped (the user already saw the error)."""
    today = today or date.today()
    employee = get_employee(db, body["user"]["id"])
    leave_type, start, end, reason, half = _parse_submission(view)
    if validate_request(db, employee, leave_type, start, end, today, half):
        return

    request_id = create_request(
        db, employee["slack_user_id"], leave_type, start, end, reason, half
    )

    # Top of chain: no manager to approve, so auto-approve.
    if employee["manager_id"] is None:
        _finalize_approval(db, calendar, request_id, employee, leave_type, start, end, half)
        _notify(
            client,
            employee["slack_user_id"],
            f"Your {leave_type} leave {format_period(start, end, half)} was auto-approved.",
        )
        update_board(
            db,
            client,
            today,
            sheets,
            add={
                "request_id": request_id,
                "name": employee["real_name"],
                "type": leave_type,
                "start": start,
                "end": end,
                "half": half,
            },
        )
        return

    remaining = remaining_balance(db, employee, leave_type, today)
    blocks = build_ticket(
        request_id, employee["real_name"], leave_type, start, end, reason, remaining, half
    )
    resp = client.chat_postMessage(
        channel=employee["manager_id"],
        text=f"{employee['real_name']} requests {leave_type} leave",
        blocks=blocks,
    )
    # Remember the ticket message so it can be withdrawn if the employee cancels.
    set_ticket_ref(db, request_id, resp["channel"], resp["ts"])


def submit_leave(ack, body, view, client, db, calendar, sheets=None, today=None):
    """Synchronous submit (Socket Mode / tests): ack-with-validation, then apply."""
    if submit_leave_ack(ack, body, view, db, today):
        submit_leave_apply(body, view, client, db, calendar, sheets, today)


def _notify(client, employee_id, text):
    client.chat_postMessage(channel=employee_id, text=text)


def _close_stale_ticket(client, channel, ts, request):
    """A decision was attempted on a request that is no longer pending (it was
    cancelled, or already decided). Replace the ticket so its buttons vanish."""
    client.chat_update(
        channel=channel,
        ts=ts,
        text="No longer actionable",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"This request is no longer pending — it was {request['status']}. "
                    "No action taken.",
                },
            }
        ],
    )


def handle_approve(ack, body, client, db, calendar, sheets=None, today=None):
    ack()
    today = today or date.today()
    request_id = body["actions"][0]["value"]
    request = get_request(db, request_id)
    employee = get_employee(db, request["employee_id"])

    if body["user"]["id"] != employee["manager_id"]:
        _notify(client, body["user"]["id"], NOT_APPROVER)
        return
    if request["status"] != "pending":
        _close_stale_ticket(client, body["channel"]["id"], body["message"]["ts"], request)
        return

    _finalize_approval(
        db,
        calendar,
        request_id,
        employee,
        request["leave_type"],
        request["start_date"],
        request["end_date"],
        request.get("half"),
    )
    client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        text="Approved",
        blocks=build_decision_notice(
            employee["real_name"],
            request["leave_type"],
            request["start_date"],
            request["end_date"],
            "✅ Approved",
            half=request.get("half"),
        ),
    )
    _notify(
        client,
        employee["slack_user_id"],
        f"Your {request['leave_type']} leave "
        f"{format_period(request['start_date'], request['end_date'], request.get('half'))} was approved.",
    )
    update_board(
        db,
        client,
        today,
        sheets,
        add={
            "request_id": request_id,
            "name": employee["real_name"],
            "type": request["leave_type"],
            "start": request["start_date"],
            "end": request["end_date"],
            "half": request.get("half"),
        },
    )


def handle_decline_click(ack, body, client, db):
    ack()
    request_id = body["actions"][0]["value"]
    request = get_request(db, request_id)
    if request["status"] != "pending":
        _close_stale_ticket(client, body["channel"]["id"], body["message"]["ts"], request)
        return
    meta = json.dumps(
        {
            "request_id": body["actions"][0]["value"],
            "channel": body["channel"]["id"],
            "ts": body["message"]["ts"],
        }
    )
    client.views_open(trigger_id=body["trigger_id"], view=build_decline_modal(meta))


def handle_decline_submit(ack, body, view, client, db):
    ack()
    meta = json.loads(view["private_metadata"])
    request_id = meta["request_id"]
    reason = view["state"]["values"]["decline_reason"]["value"].get("value")

    request = get_request(db, request_id)
    employee = get_employee(db, request["employee_id"])
    if body["user"]["id"] != employee["manager_id"]:
        return
    if request["status"] != "pending":
        _close_stale_ticket(client, meta["channel"], meta["ts"], request)
        return

    decline_request(db, request_id, reason)
    client.chat_update(
        channel=meta["channel"],
        ts=meta["ts"],
        text="Declined",
        blocks=build_decision_notice(
            employee["real_name"],
            request["leave_type"],
            request["start_date"],
            request["end_date"],
            "❌ Declined",
            reason,
            half=request.get("half"),
        ),
    )
    text = (
        f"Your {request['leave_type']} leave "
        f"{format_period(request['start_date'], request['end_date'], request.get('half'))} was declined."
    )
    if reason:
        text += f" Reason: {reason}"
    _notify(client, employee["slack_user_id"], text)


def open_cancel_modal(ack, body, client, db, today=None):
    today = today or date.today()
    employee = get_employee(db, body["user_id"])
    if employee is None:
        ack(CONTACT_ADMIN)
        return
    rows = cancellable_requests(db, employee["slack_user_id"], today)
    if not rows:
        ack(NOTHING_TO_CANCEL)
        return
    ack()
    client.views_open(trigger_id=body["trigger_id"], view=build_cancel_modal(rows))


def submit_cancel(ack, body, view, client, db, calendar, sheets=None, today=None):
    ack()
    today = today or date.today()
    request_id = view["state"]["values"]["request"]["value"]["selected_option"]["value"]
    request = get_request(db, request_id)

    if body["user"]["id"] != request["employee_id"]:
        return
    if not can_cancel(request, today):
        _notify(client, body["user"]["id"], CANNOT_CANCEL)
        return

    status_before = request["status"]
    cancel_request(db, request_id)
    employee = get_employee(db, request["employee_id"])

    if status_before == "pending" and request["ticket_ts"]:
        # Withdraw the manager's still-open ticket so its buttons disappear.
        client.chat_update(
            channel=request["ticket_channel"],
            ts=request["ticket_ts"],
            text="Request withdrawn",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{employee['real_name']} withdrew this {request['leave_type']} "
                        "request before a decision.",
                    },
                }
            ],
        )

    if status_before == "approved" and request["calendar_event_id"]:
        calendar.delete_event(request["calendar_event_id"])
        update_board(db, client, today, sheets, remove_request_id=request_id)
        if employee["manager_id"]:
            _notify(
                client,
                employee["manager_id"],
                f"FYI: {employee['real_name']} cancelled their {request['leave_type']} "
                f"leave {format_period(request['start_date'], request['end_date'], request.get('half'))}.",
            )

    _notify(
        client,
        body["user"]["id"],
        f"Cancelled your {request['leave_type']} leave "
        f"{format_period(request['start_date'], request['end_date'], request.get('half'))}.",
    )
