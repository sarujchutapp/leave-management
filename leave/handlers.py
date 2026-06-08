"""Slack handler logic, written as plain functions so tests can pass fakes.

app.py registers these on the Bolt app, supplying a real DB connection; Bolt
injects ack/body/view/client/logger by parameter name.
"""

from leave.blocks import build_leave_modal
from leave.db import get_employee

CONTACT_ADMIN = "You're not set up in the leave system yet — please contact your admin."


def open_leave_modal(ack, body, client, conn):
    employee = get_employee(conn, body["user_id"])
    if employee is None:
        ack(CONTACT_ADMIN)
        return
    ack()
    client.views_open(trigger_id=body["trigger_id"], view=build_leave_modal())


def submit_leave(ack, view, logger):
    # Slice 2: acknowledge and log. Validation and persistence come in later slices.
    ack()
    values = view["state"]["values"]
    logger.info("Leave submission received: %s", values)
