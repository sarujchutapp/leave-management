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
    ADVANCE_BOOK_ACTION,
    APPROVE_ACTION,
    CANCEL_CALLBACK_ID,
    GROUP_CALLBACK_ID,
    GROUP_PICK_ACTION,
    CARRY_OVER_ACTION,
    CARRY_OVER_CALLBACK_ID,
    CARRY_OVER_TOGGLE_ACTION,
    CONSECUTIVE_TOGGLE_ACTION,
    CLEAR_ACTION,
    CLEAR_CALLBACK_ID,
    HOLIDAYS_ACTION,
    HOLIDAYS_CALLBACK_ID,
    DECLINE_ACTION,
    DECLINE_CALLBACK_ID,
    LEAVE_CALLBACK_ID,
    LEAVE_LIMITS_ACTION,
    LEAVE_LIMITS_CALLBACK_ID,
    MANAGE_ACTION_SELECT,
    BURNOUT_REFRESH_ACTION,
    MANAGE_EMPLOYEES_ACTION,
    MANAGE_EMPLOYEES_CALLBACK_ID,
    NUDGE_ACTION,
    REPORT_ACTION,
    REPORT_CALLBACK_ID,
    REPORT_TYPE_ACTION,
    VIEW_SETTINGS_ACTION,
)
from leave.handlers import (
    handle_approve,
    handle_decline_click,
    handle_decline_submit,
    handle_nudge,
    open_advance,
    open_book_modal,
    open_burnout,
    open_burnout_ack,
    open_burnout_apply,
    refresh_burnout,
    open_cancel_modal,
    open_group_picker,
    open_holidays,
    open_carry_over,
    open_clear,
    open_control_menu,
    open_leave_limits,
    open_leave_modal,
    open_manage_employees,
    update_manage_modal,
    update_carry_over_modal,
    update_leave_limits_modal,
    open_report,
    open_view_settings,
    update_report_modal,
    submit_cancel,
    submit_carry_over,
    submit_carry_over_ack,
    submit_carry_over_apply,
    submit_clear,
    submit_clear_ack,
    submit_clear_apply,
    submit_group_break,
    submit_group_break_ack,
    submit_group_break_apply,
    submit_holidays,
    submit_holidays_ack,
    submit_holidays_apply,
    submit_leave,
    submit_leave_ack,
    submit_leave_apply,
    submit_leave_limits,
    submit_manage_employees,
    submit_manage_employees_ack,
    submit_manage_employees_apply,
    submit_report,
    submit_report_ack,
    submit_report_apply,
)

load_dotenv()


def _ack(ack):
    ack()


def _noop_ack(*args, **kwargs):
    """Ack placeholder for handlers invoked as lazy listeners — the real ack
    already ran in the ack phase, so the handler's own ack() call is a no-op."""


def _admin_ids():
    """Slack member IDs allowed to use /control, from the non-secret SLACK_ADMIN_IDS
    env var (comma-separated). Empty/unset means no admins."""
    raw = os.environ.get("SLACK_ADMIN_IDS", "")
    return {x.strip() for x in raw.split(",") if x.strip()}


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

    # /advance only reads (balance, holidays, leave, policy) and opens one keyed
    # modal — no slow calendar/board work — so it runs synchronously in both run
    # modes, like /control.
    @app.command("/advance")
    def _advance(ack, body, client):
        with db.connect() as d:
            open_advance(ack, body, client, d)

    # Book button on a suggested break: opens the apply modal pre-filled (needs
    # the trigger_id within 3s), so it runs synchronously like other modal opens.
    @app.action(ADVANCE_BOOK_ACTION)
    def _advance_book(ack, body, client):
        with db.connect() as d:
            open_book_modal(ack, body, client, d)

    # "Plan a group break" button: opens the people-picker modal (fast).
    @app.action(GROUP_PICK_ACTION)
    def _group_pick(ack, body, client):
        open_group_picker(ack, body, client)

    # Admin control plane. The menu open + View Settings only open modals / do a
    # keyed policy read (fast), so they run synchronously in both run modes. The
    # admin allowlist is injected, not read inside the handlers.
    admin_ids = _admin_ids()

    @app.command("/control")
    def _control(ack, body, client):
        open_control_menu(ack, body, client, admin_ids)

    @app.action(VIEW_SETTINGS_ACTION)
    def _view_settings(ack, body, client):
        with db.connect() as d:
            open_view_settings(ack, body, client, d, admin_ids)

    @app.action(LEAVE_LIMITS_ACTION)
    def _leave_limits(ack, body, client):
        with db.connect() as d:
            open_leave_limits(ack, body, client, d, admin_ids)

    # Enforce-consecutive-limit checkbox: re-render the modal in place (fast).
    @app.action(CONSECUTIVE_TOGGLE_ACTION)
    def _consecutive_toggle(ack, body, client):
        with db.connect() as d:
            update_leave_limits_modal(ack, body, client, d, admin_ids)

    # Leave-limits submit is validate + a single PutItem (fast, well under 3s), so
    # it runs synchronously in both run modes rather than as a lazy listener.
    @app.view(LEAVE_LIMITS_CALLBACK_ID)
    def _leave_limits_submit(ack, body, view, client):
        with db.connect() as d:
            submit_leave_limits(ack, body, view, client, d, admin_ids)

    @app.action(CARRY_OVER_ACTION)
    def _carry_over(ack, body, client):
        with db.connect() as d:
            open_carry_over(ack, body, client, d, admin_ids)

    # Enable-carry-over checkbox: re-render the modal in place (fast).
    @app.action(CARRY_OVER_TOGGLE_ACTION)
    def _carry_over_toggle(ack, body, client):
        with db.connect() as d:
            update_carry_over_modal(ack, body, client, d, admin_ids)

    @app.action(CLEAR_ACTION)
    def _clear(ack, body, client):
        open_clear(ack, body, client, admin_ids)

    @app.action(MANAGE_EMPLOYEES_ACTION)
    def _manage_employees(ack, body, client):
        open_manage_employees(ack, body, client, admin_ids)

    @app.action(HOLIDAYS_ACTION)
    def _holidays(ack, body, client):
        with db.connect() as d:
            open_holidays(ack, body, client, d, admin_ids)

    @app.action(MANAGE_ACTION_SELECT)
    def _manage_action_changed(ack, body, client):
        update_manage_modal(ack, body, client, admin_ids)

    @app.action(REPORT_ACTION)
    def _report(ack, body, client):
        with db.connect() as d:
            open_report(ack, body, client, d, admin_ids)

    @app.action(REPORT_TYPE_ACTION)
    def _report_type_changed(ack, body, client):
        with db.connect() as d:
            update_report_modal(ack, body, client, d, admin_ids)

    @app.action(DECLINE_ACTION)
    def _decline_click(ack, body, client):
        with db.connect() as d:
            handle_decline_click(ack, body, client, d)

    # Approve / decline-submit / cancel — and the /dayoff submit — do slow post-ack
    # work (Google Calendar/Sheets API calls, manager DMs). On Lambda they run as lazy
    # listeners so the ack still returns within Slack's 3s window; in Socket Mode they
    # run inline. The submit's ack phase only validates (fast); building the Google
    # clients and writing the calendar/board happen in the lazy phase.
    if faas:

        def _submit_ack(ack, body, view):
            with db.connect() as d:
                submit_leave_ack(ack, body, view, d)

        def _submit_lazy(body, view, client):
            with db.connect() as d:
                submit_leave_apply(body, view, client, d, get_calendar(), get_sheets())

        app.view(LEAVE_CALLBACK_ID)(ack=_submit_ack, lazy=[_submit_lazy])

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

        # Report submit: validate the choice in the ack phase (closes the modal),
        # then build the CSV (a Scan for quota) + upload post-ack.
        def _report_ack(ack, body, view):
            submit_report_ack(ack, body, view, admin_ids)

        def _report_lazy(body, view, client):
            with db.connect() as d:
                submit_report_apply(body, view, d, client, admin_ids)

        app.view(REPORT_CALLBACK_ID)(ack=_report_ack, lazy=[_report_lazy])

        # Carry-over submit: write the caps in the ack phase, then recompute every
        # employee's stored carry_in post-ack (a Scan) so the ack stays under 3s.
        def _carry_over_ack(ack, body, view):
            with db.connect() as d:
                submit_carry_over_ack(ack, body, view, d, admin_ids)

        def _carry_over_lazy(body, view, client):
            with db.connect() as d:
                submit_carry_over_apply(body, view, d, client, admin_ids)

        app.view(CARRY_OVER_CALLBACK_ID)(ack=_carry_over_ack, lazy=[_carry_over_lazy])

        # Clear submit: confirm in the ack phase, then wipe post-ack (scan + deletes
        # + calendar API + board), so the ack stays under 3s.
        def _clear_ack(ack, body, view):
            submit_clear_ack(ack, body, view, admin_ids)

        def _clear_lazy(body, view, client):
            with db.connect() as d:
                submit_clear_apply(body, view, d, get_calendar(), get_sheets(), client, admin_ids)

        app.view(CLEAR_CALLBACK_ID)(ack=_clear_ack, lazy=[_clear_lazy])

        # Holidays submit: validate in the ack phase, then mirror the calendar +
        # store the change post-ack (the Google Calendar call is the slow part).
        def _holidays_ack(ack, body, view):
            submit_holidays_ack(ack, body, view, admin_ids)

        def _holidays_lazy(body, view, client):
            with db.connect() as d:
                submit_holidays_apply(body, view, d, get_calendar(), client, admin_ids)

        app.view(HOLIDAYS_CALLBACK_ID)(ack=_holidays_ack, lazy=[_holidays_lazy])

        # Manage-employees submit: validate + close the modal in the ack phase, then do
        # the write post-ack. Delete and a manager change settle the person's in-flight
        # leave (calendar/board/ticket cleanup — slow Slack/calendar calls), so the work
        # must run lazily to keep the ack under 3s.
        def _manage_ack(ack, body, view, client):
            with db.connect() as d:
                submit_manage_employees_ack(ack, body, view, client, d, admin_ids)

        def _manage_lazy(body, view, client):
            with db.connect() as d:
                submit_manage_employees_apply(
                    body, view, client, d, admin_ids, get_calendar(), get_sheets()
                )

        app.view(MANAGE_EMPLOYEES_CALLBACK_ID)(ack=_manage_ack, lazy=[_manage_lazy])

        # Group-break submit: the ack rejects a bot pick (inline error) or closes the
        # picker, then the multi-person search + DM run post-ack so the ack stays
        # under 3s for larger groups. The lazy apply re-checks bots (it fires
        # regardless of the ack).
        def _group_break_ack(ack, view, client):
            submit_group_break_ack(ack, view, client)

        def _group_break_lazy(body, view, client):
            with db.connect() as d:
                submit_group_break_apply(body, view, client, d)

        app.view(GROUP_CALLBACK_ID)(ack=_group_break_ack, lazy=[_group_break_lazy])

        # /burnout: the manager gate + loading-modal open ack within 3s, then the
        # board (several record reads) is built + swapped in post-ack as a lazy
        # listener (the trigger_id only lives 3s, so the modal opens empty first).
        def _burnout_ack(ack, body, client):
            with db.connect() as d:
                open_burnout_ack(ack, body, client, d)

        def _burnout_lazy(body, client):
            with db.connect() as d:
                open_burnout_apply(body, d, client)

        app.command("/burnout")(ack=_burnout_ack, lazy=[_burnout_lazy])

        # Refresh button: ack at once, then rebuild the open board modal post-ack.
        def _burnout_refresh_lazy(body, client):
            with db.connect() as d:
                refresh_burnout(_noop_ack, body, client, d)

        app.action(BURNOUT_REFRESH_ACTION)(ack=_ack, lazy=[_burnout_refresh_lazy])

        # Nudge button: ack the click at once, then the bot DMs the report + flips the
        # row to "Nudged" in the modal post-ack (no DB — it books nothing).
        def _nudge_lazy(body, client):
            handle_nudge(_noop_ack, body, client)

        app.action(NUDGE_ACTION)(ack=_ack, lazy=[_nudge_lazy])
    else:

        @app.view(LEAVE_CALLBACK_ID)
        def _submit(ack, body, view, client):
            with db.connect() as d:
                submit_leave(ack, body, view, client, d, get_calendar(), get_sheets())

        @app.view(CARRY_OVER_CALLBACK_ID)
        def _carry_over_submit(ack, body, view, client):
            with db.connect() as d:
                submit_carry_over(ack, body, view, client, d, admin_ids)

        @app.view(CLEAR_CALLBACK_ID)
        def _clear_submit(ack, body, view, client):
            with db.connect() as d:
                submit_clear(ack, body, view, d, get_calendar(), get_sheets(), client, admin_ids)

        @app.action(APPROVE_ACTION)
        def _approve(ack, body, client):
            with db.connect() as d:
                handle_approve(ack, body, client, d, get_calendar(), get_sheets())

        @app.view(DECLINE_CALLBACK_ID)
        def _decline_submit(ack, body, view, client):
            with db.connect() as d:
                handle_decline_submit(ack, body, view, client, d)

        @app.view(GROUP_CALLBACK_ID)
        def _group_break_submit(ack, body, view, client):
            with db.connect() as d:
                submit_group_break(ack, body, view, client, d)

        @app.view(HOLIDAYS_CALLBACK_ID)
        def _holidays_submit(ack, body, view, client):
            with db.connect() as d:
                submit_holidays(ack, body, view, d, get_calendar(), client, admin_ids)

        @app.view(MANAGE_EMPLOYEES_CALLBACK_ID)
        def _manage_employees_submit(ack, body, view, client):
            with db.connect() as d:
                submit_manage_employees(
                    ack, body, view, client, d, admin_ids, get_calendar(), get_sheets()
                )

        @app.view(CANCEL_CALLBACK_ID)
        def _cancel(ack, body, view, client):
            with db.connect() as d:
                submit_cancel(ack, body, view, client, d, get_calendar(), get_sheets())

        @app.view(REPORT_CALLBACK_ID)
        def _report_submit(ack, body, view, client):
            with db.connect() as d:
                submit_report(ack, body, view, d, client, admin_ids)

        @app.command("/burnout")
        def _burnout(ack, body, client):
            with db.connect() as d:
                open_burnout(ack, body, d, client)

        @app.action(BURNOUT_REFRESH_ACTION)
        def _burnout_refresh(ack, body, client):
            with db.connect() as d:
                refresh_burnout(ack, body, client, d)

        @app.action(NUDGE_ACTION)
        def _nudge(ack, body, client):
            handle_nudge(ack, body, client)

    return app


def main():
    app = build_app()
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


if __name__ == "__main__":
    main()
