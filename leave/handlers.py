"""Slack handler logic, written as plain functions so tests can pass fakes.

app.py registers these on the Bolt app, supplying a real DB connection; Bolt
injects ack/body/view/client/logger by parameter name.
"""

import json
from datetime import date

from leave.blocks import (
    build_cancel_modal,
    build_decision_notice,
    build_decline_modal,
    build_leave_modal,
    build_ticket,
)
from leave.board import update_board
from leave.db import get_employee
from leave.requests import (
    approve_request,
    can_cancel,
    cancel_request,
    cancellable_requests,
    create_request,
    decline_request,
    get_request,
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
    """Mark approved and create the shared-calendar event, storing its id."""
    approve_request(db, request_id)
    summary = f"{employee['real_name']} — {leave_type}"
    if half:
        summary += f" ({half})"
    event_id = calendar.create_event(summary, start, end)
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
            f"Your {leave_type} leave {start} → {end} was auto-approved.",
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
        request_id, employee["real_name"], leave_type, start, end, reason, remaining
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
        ),
    )
    _notify(
        client,
        employee["slack_user_id"],
        f"Your {request['leave_type']} leave {request['start_date']} → {request['end_date']} was approved.",
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
        ),
    )
    text = f"Your {request['leave_type']} leave {request['start_date']} → {request['end_date']} was declined."
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
                f"leave {request['start_date']} → {request['end_date']}.",
            )

    _notify(
        client,
        body["user"]["id"],
        f"Cancelled your {request['leave_type']} leave "
        f"{request['start_date']} → {request['end_date']}.",
    )
