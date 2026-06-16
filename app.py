"""Bolt app factory + the Socket Mode entrypoint used for local development.

`build_app()` is shared by both run modes:
- Local dev: `python app.py` runs it over Socket Mode (a persistent WebSocket).
- Production: `lambda_handler.handler` runs it over HTTP on AWS Lambda — see
  issue #17. Pass `faas=True` there so the slow handlers run as lazy listeners
  and the App responds before processing (required on FaaS).
"""

import os

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from leave import db
from leave.calendar_client import CalendarClient
from leave.sheets_client import SheetsClient
from leave.blocks import (
    APPROVE_ACTION,
    CANCEL_CALLBACK_ID,
    DECLINE_ACTION,
    DECLINE_CALLBACK_ID,
    LEAVE_CALLBACK_ID,
)
from leave.handlers import (
    handle_approve,
    handle_decline_click,
    handle_decline_submit,
    open_cancel_modal,
    open_leave_modal,
    submit_cancel,
    submit_leave,
)

load_dotenv()


def _ack(ack):
    ack()


def _noop_ack(*args, **kwargs):
    """Ack placeholder for handlers invoked as lazy listeners — the real ack
    already ran in the ack phase, so the handler's own ack() call is a no-op."""


def build_app(calendar=None, faas=False):
    app = App(
        token=os.environ["SLACK_BOT_TOKEN"],
        signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
        process_before_response=faas,
        # smoke_check.py validates the bot token; skipping the startup auth.test
        # keeps Socket Mode fast and avoids a network call on every Lambda cold start.
        token_verification_enabled=False,
    )
    # Build the Google Calendar client lazily. Only the approve / cancel / auto-approve
    # paths use it, and `CalendarClient.from_env()` runs `discovery.build`, which is slow.
    # Building it eagerly here would add that cost to every cold start — including the
    # `/dayoff` modal open, which never touches the calendar — and can trip Slack's 3s
    # ack window. An injected client (tests) is used as-is; otherwise it's constructed on
    # first use and reused for the life of the warm instance.
    _calendar = calendar

    def get_calendar():
        nonlocal _calendar
        if _calendar is None:
            _calendar = CalendarClient.from_env()
        return _calendar

    # Built lazily and only when the leave board is configured (LEAVE_SHEET_ID set),
    # so cold-start paths that never render the board skip the heavy Sheets import.
    _sheets = None

    def get_sheets():
        nonlocal _sheets
        if _sheets is None and os.environ.get("LEAVE_SHEET_ID"):
            _sheets = SheetsClient.from_env()
        return _sheets

    # These open modals (need the trigger_id within 3s) or return validation errors
    # in the ack itself, so they must run synchronously, not as lazy listeners.
    @app.command("/dayoff")
    def _open(ack, body, client):
        with db.connect() as d:
            open_leave_modal(ack, body, client, d)

    @app.command("/dayoff-cancel")
    def _open_cancel(ack, body, client):
        with db.connect() as d:
            open_cancel_modal(ack, body, client, d)

    @app.action(DECLINE_ACTION)
    def _decline_click(ack, body, client):
        with db.connect() as d:
            handle_decline_click(ack, body, client, d)

    @app.view(LEAVE_CALLBACK_ID)
    def _submit(ack, body, view, client):
        with db.connect() as d:
            submit_leave(ack, body, view, client, d, get_calendar(), get_sheets())

    # Approve / decline-submit / cancel do the slow post-ack work (Google Calendar
    # API calls, manager DMs). On Lambda they run as lazy listeners so the ack still
    # returns within Slack's 3s window; in Socket Mode they run inline as before.
    if faas:

        def _approve_lazy(body, client):
            with db.connect() as d:
                handle_approve(_noop_ack, body, client, d, get_calendar(), get_sheets())

        def _decline_submit_lazy(body, view, client):
            with db.connect() as d:
                handle_decline_submit(_noop_ack, body, view, client, d)

        def _cancel_lazy(body, view, client):
            with db.connect() as d:
                submit_cancel(_noop_ack, body, view, client, d, get_calendar(), get_sheets())

        app.action(APPROVE_ACTION)(ack=_ack, lazy=[_approve_lazy])
        app.view(DECLINE_CALLBACK_ID)(ack=_ack, lazy=[_decline_submit_lazy])
        app.view(CANCEL_CALLBACK_ID)(ack=_ack, lazy=[_cancel_lazy])
    else:

        @app.action(APPROVE_ACTION)
        def _approve(ack, body, client):
            with db.connect() as d:
                handle_approve(ack, body, client, d, get_calendar(), get_sheets())

        @app.view(DECLINE_CALLBACK_ID)
        def _decline_submit(ack, body, view, client):
            with db.connect() as d:
                handle_decline_submit(ack, body, view, client, d)

        @app.view(CANCEL_CALLBACK_ID)
        def _cancel(ack, body, view, client):
            with db.connect() as d:
                submit_cancel(ack, body, view, client, d, get_calendar(), get_sheets())

    return app


def main():
    app = build_app()
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


if __name__ == "__main__":
    main()
