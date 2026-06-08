"""Entrypoint: build the Bolt app and run it over Socket Mode."""

import os

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from leave import db
from leave.calendar_client import CalendarClient
from leave.blocks import (
    APPROVE_ACTION,
    CANCEL_ACTION,
    DECLINE_ACTION,
    DECLINE_CALLBACK_ID,
    LEAVE_CALLBACK_ID,
)
from leave.handlers import (
    handle_approve,
    handle_cancel,
    handle_decline_click,
    handle_decline_submit,
    open_cancel_list,
    open_leave_modal,
    submit_leave,
)

load_dotenv()


def build_app():
    app = App(token=os.environ["SLACK_BOT_TOKEN"])
    calendar = CalendarClient.from_env()

    @app.command("/dayoff")
    def _open(ack, body, client):
        with db.connect() as conn:
            open_leave_modal(ack, body, client, conn)

    @app.view(LEAVE_CALLBACK_ID)
    def _submit(ack, body, view, client):
        with db.connect() as conn:
            submit_leave(ack, body, view, client, conn, calendar)

    @app.action(APPROVE_ACTION)
    def _approve(ack, body, client):
        with db.connect() as conn:
            handle_approve(ack, body, client, conn, calendar)

    @app.action(DECLINE_ACTION)
    def _decline_click(ack, body, client):
        handle_decline_click(ack, body, client)

    @app.view(DECLINE_CALLBACK_ID)
    def _decline_submit(ack, body, view, client):
        with db.connect() as conn:
            handle_decline_submit(ack, body, view, client, conn)

    @app.command("/dayoff-cancel")
    def _cancel_list(ack, body):
        with db.connect() as conn:
            open_cancel_list(ack, body, conn)

    @app.action(CANCEL_ACTION)
    def _cancel(ack, body, client):
        with db.connect() as conn:
            handle_cancel(ack, body, client, conn, calendar)

    return app


def main():
    app = build_app()
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


if __name__ == "__main__":
    main()
