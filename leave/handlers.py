"""Slack handler logic, written as plain functions so tests can pass fakes.

app.py registers these on the Bolt app; Bolt injects ack/body/view/client/logger
by parameter name.
"""

from leave.blocks import build_leave_modal


def open_leave_modal(ack, body, client):
    ack()
    client.views_open(trigger_id=body["trigger_id"], view=build_leave_modal())


def submit_leave(ack, view, logger):
    # Slice 2: acknowledge and log. Validation and persistence come in later slices.
    ack()
    values = view["state"]["values"]
    logger.info("Leave submission received: %s", values)
