"""Slack handler logic, written as plain functions so tests can pass fakes.

app.py registers these on the Bolt app, supplying a real DB connection; Bolt
injects ack/body/view/client/logger by parameter name.
"""

import json
from datetime import date

from leave.blocks import (
    LEAVE_TYPES,
    build_cancel_modal,
    build_decision_notice,
    build_decline_modal,
    build_leave_modal,
    build_ticket,
)
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
    set_calendar_event_id,
)
from leave.validation import validate_request

CONTACT_ADMIN = "You're not set up in the leave system yet — please contact your admin."
NOT_APPROVER = "You're not the approver for this request."
NOTHING_TO_CANCEL = "You have no requests to cancel."
CANNOT_CANCEL = "That request can no longer be cancelled."


def open_leave_modal(ack, body, client, conn, today=None):
    today = today or date.today()
    employee = get_employee(conn, body["user_id"])
    if employee is None:
        ack(CONTACT_ADMIN)
        return
    ack()
    balances = {t: remaining_balance(conn, employee, t, today) for t in LEAVE_TYPES}
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
    end = _to_gregorian(date.fromisoformat(values["end_date"]["value"]["selected_date"]))
    reason = values["reason"]["value"].get("value")
    return leave_type, start, end, reason


def _finalize_approval(conn, calendar, request_id, employee, leave_type, start, end):
    """Mark approved and create the shared-calendar event, storing its id."""
    approve_request(conn, request_id)
    event_id = calendar.create_event(f"{employee['real_name']} — {leave_type}", start, end)
    set_calendar_event_id(conn, request_id, event_id)


def submit_leave(ack, body, view, client, conn, calendar, today=None):
    today = today or date.today()
    employee = get_employee(conn, body["user"]["id"])
    leave_type, start, end, reason = _parse_submission(view)

    errors = validate_request(conn, employee, leave_type, start, end, today)
    if errors:
        ack(response_action="errors", errors=errors)
        return

    request_id = create_request(conn, employee["slack_user_id"], leave_type, start, end, reason)
    ack()

    # Top of chain: no manager to approve, so auto-approve.
    if employee["manager_id"] is None:
        _finalize_approval(conn, calendar, request_id, employee, leave_type, start, end)
        _notify(
            client,
            employee["slack_user_id"],
            f"Your {leave_type} leave {start} → {end} was auto-approved.",
        )
        return

    remaining = remaining_balance(conn, employee, leave_type, today)
    blocks = build_ticket(
        request_id, employee["real_name"], leave_type, start, end, reason, remaining
    )
    client.chat_postMessage(
        channel=employee["manager_id"],
        text=f"{employee['real_name']} requests {leave_type} leave",
        blocks=blocks,
    )


def _notify(client, employee_id, text):
    client.chat_postMessage(channel=employee_id, text=text)


def handle_approve(ack, body, client, conn, calendar):
    ack()
    request_id = int(body["actions"][0]["value"])
    request = get_request(conn, request_id)
    employee = get_employee(conn, request["employee_id"])

    if body["user"]["id"] != employee["manager_id"]:
        _notify(client, body["user"]["id"], NOT_APPROVER)
        return

    _finalize_approval(
        conn,
        calendar,
        request_id,
        employee,
        request["leave_type"],
        request["start_date"],
        request["end_date"],
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


def handle_decline_click(ack, body, client):
    ack()
    meta = json.dumps(
        {
            "request_id": body["actions"][0]["value"],
            "channel": body["channel"]["id"],
            "ts": body["message"]["ts"],
        }
    )
    client.views_open(trigger_id=body["trigger_id"], view=build_decline_modal(meta))


def handle_decline_submit(ack, body, view, client, conn):
    ack()
    meta = json.loads(view["private_metadata"])
    request_id = int(meta["request_id"])
    reason = view["state"]["values"]["decline_reason"]["value"].get("value")

    request = get_request(conn, request_id)
    employee = get_employee(conn, request["employee_id"])
    if body["user"]["id"] != employee["manager_id"]:
        return

    decline_request(conn, request_id, reason)
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


def open_cancel_modal(ack, body, client, conn, today=None):
    today = today or date.today()
    employee = get_employee(conn, body["user_id"])
    if employee is None:
        ack(CONTACT_ADMIN)
        return
    rows = cancellable_requests(conn, employee["slack_user_id"], today)
    if not rows:
        ack(NOTHING_TO_CANCEL)
        return
    ack()
    client.views_open(trigger_id=body["trigger_id"], view=build_cancel_modal(rows))


def submit_cancel(ack, body, view, client, conn, calendar, today=None):
    ack()
    today = today or date.today()
    request_id = int(view["state"]["values"]["request"]["value"]["selected_option"]["value"])
    request = get_request(conn, request_id)

    if body["user"]["id"] != request["employee_id"]:
        return
    if not can_cancel(request, today):
        _notify(client, body["user"]["id"], CANNOT_CANCEL)
        return

    was_approved = request["status"] == "approved"
    cancel_request(conn, request_id)

    if was_approved and request["calendar_event_id"]:
        calendar.delete_event(request["calendar_event_id"])
        employee = get_employee(conn, request["employee_id"])
        if employee["manager_id"]:
            _notify(
                client,
                employee["manager_id"],
                f"FYI: {employee['real_name']} cancelled their {request['leave_type']} "
                f"leave {request['start_date']} → {request['end_date']}.",
            )

    _notify(client, body["user"]["id"], "Your request was cancelled.")
