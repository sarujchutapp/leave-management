"""Slack handler logic, written as plain functions so tests can pass fakes.

app.py registers these on the Bolt app, supplying a real DB connection; Bolt
injects ack/body/view/client/logger by parameter name.
"""

from datetime import date

from leave.blocks import LEAVE_TYPES, build_leave_modal
from leave.db import get_employee
from leave.requests import create_request, remaining_balance
from leave.validation import validate_request

CONTACT_ADMIN = "You're not set up in the leave system yet — please contact your admin."


def open_leave_modal(ack, body, client, conn, today=None):
    today = today or date.today()
    employee = get_employee(conn, body["user_id"])
    if employee is None:
        ack(CONTACT_ADMIN)
        return
    ack()
    balances = {t: remaining_balance(conn, employee, t, today) for t in LEAVE_TYPES}
    client.views_open(trigger_id=body["trigger_id"], view=build_leave_modal(balances))


def _parse_submission(view):
    values = view["state"]["values"]
    leave_type = values["leave_type"]["value"]["selected_option"]["value"]
    start = date.fromisoformat(values["start_date"]["value"]["selected_date"])
    end = date.fromisoformat(values["end_date"]["value"]["selected_date"])
    reason = values["reason"]["value"].get("value")
    return leave_type, start, end, reason


def submit_leave(ack, body, view, conn, today=None):
    today = today or date.today()
    employee = get_employee(conn, body["user"]["id"])
    leave_type, start, end, reason = _parse_submission(view)

    errors = validate_request(conn, employee, leave_type, start, end, today)
    if errors:
        ack(response_action="errors", errors=errors)
        return

    create_request(conn, employee["slack_user_id"], leave_type, start, end, reason)
    ack()
