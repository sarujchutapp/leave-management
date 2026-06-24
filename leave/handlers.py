"""Slack handler logic, written as plain functions so tests can pass fakes.

app.py registers these on the Bolt app, supplying a real DB connection; Bolt
injects ack/body/view/client/logger by parameter name.
"""

import json
from datetime import date

from leave.blocks import (
    CLEAR_CONFIRM_WORD,
    REPORT_TYPE_ACTION,
    build_advance_blocks,
    build_cancel_modal,
    build_group_picker_modal,
    build_group_result_blocks,
    build_carry_over_modal,
    build_clear_modal,
    build_control_menu,
    build_decision_notice,
    build_decline_modal,
    build_leave_limits_modal,
    build_leave_modal,
    build_manage_employees_modal,
    build_report_modal,
    build_settings_view,
    build_ticket,
    format_period,
)
from leave.board import update_board
from leave.calendar_client import color_id_for
from leave.db import get_employee, list_reports
from leave.policy import get_policy, set_policy
from leave.report import build_burnout_csv, build_history_csv, build_report_csv
from leave.seed import delete_employee, upsert_employee
from leave.coverage import format_coverage_warning, peer_overlap
from leave.holidays import holidays_for_year
from leave.optimizer import Member, group_break, top_breaks
from leave.requests import (
    active_full_leave_ranges,
    approve_request,
    pending_approved_intervals,
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
ADVANCE_NOTHING = (
    "No vacation break to suggest right now — you may be out of vacation balance, "
    "or have no open stretch left this year."
)
GROUP_NO_WINDOW = (
    "No window found where everyone can be off together in the rest of the year — "
    "try a smaller group or different people."
)


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


def submit_leave_limits(ack, body, view, client, db, admin_ids):
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
    ack(response_action="clear")  # close the whole modal stack on success
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
    _notify(
        client,
        body["user"]["id"],
        f"✅ Leave limits updated — sick {parsed['sick']}, vacation {parsed['vacation']}, "
        f"personal {parsed['personal']}, consecutive limit {parsed['consecutive_limit']}.",
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
    ack(response_action="clear")  # close the whole modal stack on success
    policy = get_policy(db)
    set_policy(
        db,
        allowances=policy["allowances"],
        max_carry_over={"vacation": parsed["max_carry_over"]},
        max_total={"vacation": parsed["max_total"]},
        consecutive_limit=policy["consecutive_limit"],
    )
    return True


def submit_carry_over_apply(body, view, db, client, admin_ids, today=None):
    """Post-ack work: rebuild every employee's stored carry_in under the new caps,
    then DM the admin the result. Re-checks admin + validity because Lambda lazy
    listeners fire regardless of the ack result; an invalid/non-admin submission is
    dropped (no recompute)."""
    today = today or date.today()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    _, errors = _parse_carry_over(view)
    if errors:
        return
    count = recompute_all_carry_in(db, today.year)
    _notify(
        client,
        body["user"]["id"],
        f"♻️ Carry-over caps saved and carry-in recomputed for {count} employee(s).",
    )


def submit_carry_over(ack, body, view, client, db, admin_ids, today=None):
    """Synchronous submit (Socket Mode / tests): ack-with-validation, then recompute."""
    if submit_carry_over_ack(ack, body, view, db, admin_ids):
        submit_carry_over_apply(body, view, db, client, admin_ids, today)


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
    ack(response_action="clear")  # close the whole modal stack on success
    return True


def submit_clear_apply(body, view, db, calendar, sheets, client, admin_ids, today=None):
    """Post-ack work: the actual wipe, then DM the admin the result. Re-checks admin +
    confirmation because Lambda lazy listeners fire regardless of the ack result; an
    unconfirmed submission is dropped (nothing deleted)."""
    today = today or date.today()
    if not is_admin(body["user"]["id"], admin_ids) or not _clear_confirmed(view):
        return
    count = clear_all_requests(db, calendar, sheets, today)
    _notify(
        client,
        body["user"]["id"],
        f"🧹 Cleared {count} leave request(s), removed their calendar events, and reset the board.",
    )


def submit_clear(ack, body, view, db, calendar, sheets, client, admin_ids, today=None):
    """Synchronous submit (Socket Mode / tests): ack-with-confirmation, then wipe."""
    if submit_clear_ack(ack, body, view, admin_ids):
        submit_clear_apply(body, view, db, calendar, sheets, client, admin_ids, today)


def open_report(ack, body, client, admin_ids):
    """Report button: re-checks admin, then pushes the report-type modal (quota by
    default — the person picker only appears once 'history' is selected)."""
    ack()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    client.views_push(trigger_id=body["trigger_id"], view=build_report_modal())


def update_report_modal(ack, body, client, admin_ids):
    """Report-type select changed: re-render the modal so the person picker shows
    only for 'history'. Updates in place by view_id (no new modal)."""
    ack()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    report_type = body["actions"][0]["selected_option"]["value"]
    client.views_update(view_id=body["view"]["id"], view=build_report_modal(report_type))


def _report_choice(view):
    values = view["state"]["values"]
    report_type = values["report_type"][REPORT_TYPE_ACTION]["selected_option"]["value"]
    person = values.get("person", {}).get("value", {}).get("selected_user")
    return report_type, person


def submit_report_ack(ack, body, view, admin_ids):
    """Ack phase (under 3s): re-check admin and validate the choice. A history
    report needs a person picked. Returns True so the caller builds + sends."""
    if not is_admin(body["user"]["id"], admin_ids):
        ack()
        return False
    report_type, person = _report_choice(view)
    if report_type == "history" and not person:
        ack(response_action="errors", errors={"person": "Pick the person whose history you want."})
        return False
    ack(response_action="clear")  # close the whole modal stack on success
    return True


def _dm_csv(client, user_id, csv_text, filename, title, intro):
    """DM a CSV to the user via chat:write (auto-opens the IM; the response carries
    the DM channel id), then upload the file there. No im:write scope needed."""
    dm = client.chat_postMessage(channel=user_id, text=intro)
    client.files_upload_v2(channel=dm["channel"], content=csv_text, filename=filename, title=title)


def submit_report_apply(body, view, db, client, admin_ids, today=None):
    """Post-ack work: build the chosen CSV and DM it to the requesting admin. Re-checks
    admin + the choice because Lambda lazy listeners fire regardless of the ack."""
    today = today or date.today()
    user_id = body["user"]["id"]
    if not is_admin(user_id, admin_ids):
        return
    report_type, person = _report_choice(view)
    if report_type == "history":
        if not person:
            return
        employee = get_employee(db, person)
        name = (employee or {}).get("real_name", person)
        _dm_csv(
            client,
            user_id,
            build_history_csv(db, person),
            f"leave-history-{person}.csv",
            f"Leave history — {name}",
            f"Leave history for {name}:",
        )
    elif report_type == "burnout":
        _dm_csv(
            client,
            user_id,
            build_burnout_csv(db, today),
            "leave-burnout.csv",
            "Team burnout risk",
            "Here's the team burnout-risk report (ranked by no-break stretch):",
        )
    else:
        _dm_csv(
            client,
            user_id,
            build_report_csv(db, today),
            "leave-report.csv",
            "Leave usage report",
            "Here's the all-employee leave usage report:",
        )


def submit_report(ack, body, view, db, client, admin_ids, today=None):
    """Synchronous submit (Socket Mode / tests): ack-with-validation, then build + DM."""
    if submit_report_ack(ack, body, view, admin_ids):
        submit_report_apply(body, view, db, client, admin_ids, today)


_OVERRIDE_TYPES = ("sick", "vacation", "personal")


def open_manage_employees(ack, body, client, admin_ids):
    """Manage employees button: re-checks admin, then pushes the add/edit/delete modal."""
    ack()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    client.views_push(trigger_id=body["trigger_id"], view=build_manage_employees_modal())


def _value(values, block_id):
    return values.get(block_id, {}).get("value", {})


def _parse_overrides(values):
    """(allowances-or-None, errors). Only the non-blank per-type fields are written,
    so a partial override falls back to central policy for the rest."""
    parsed, errors = {}, {}
    for leave_type in _OVERRIDE_TYPES:
        raw = _value(values, f"override_{leave_type}").get("value")
        if raw is None or raw.strip() == "":
            continue
        n, err = _parse_int(raw)
        if err:
            errors[f"override_{leave_type}"] = err
        else:
            parsed[leave_type] = n
    return (parsed or None), errors


def submit_manage_employees(ack, body, view, client, db, admin_ids):
    """Add/edit (upsert) or delete an employee. Delete is block-and-tell: if the
    target still manages anyone, the submit is rejected naming those reports and
    nothing is deleted — no automatic re-parenting."""
    if not is_admin(body["user"]["id"], admin_ids):
        ack()
        return
    values = view["state"]["values"]
    target = _value(values, "employee").get("selected_user")
    action = _value(values, "action").get("selected_option", {}).get("value")

    if action == "delete":
        reports = [r for r in list_reports(db, target) if r["slack_user_id"] != target]
        if reports:
            names = ", ".join(sorted(r.get("real_name", r["slack_user_id"]) for r in reports))
            ack(
                response_action="errors",
                errors={
                    "employee": f"Still the manager of {names}. Re-assign them first, then delete."
                },
            )
            return
        ack(response_action="clear")  # close the whole modal stack on success
        delete_employee(db, target)
        _notify(client, body["user"]["id"], f"🗑️ Removed <@{target}> from the leave system.")
        return

    name = (_value(values, "name").get("value") or "").strip()
    overrides, errors = _parse_overrides(values)
    if not name:
        errors["name"] = "Name is required to add or edit."
    if errors:
        ack(response_action="errors", errors=errors)
        return
    ack(response_action="clear")  # close the whole modal stack on success
    manager = _value(values, "manager").get("selected_user")
    upsert_employee(db, target, name, manager, allowances=overrides)
    _notify(client, body["user"]["id"], f"✅ Saved {name} (<@{target}>).")


def open_leave_modal(ack, body, client, db, today=None):
    today = today or date.today()
    employee = get_employee(db, body["user_id"])
    if employee is None:
        ack(CONTACT_ADMIN)
        return
    ack()
    balances = remaining_balances(db, employee, today)
    client.views_open(trigger_id=body["trigger_id"], view=build_leave_modal(balances))


def _suggest_breaks(db, employee, today):
    """Gather the optimizer's inputs from the db and return the caller's top
    distinct bookable vacation breaks this year (longest-first, up to 3). Sources
    balance, holidays, existing full-day leave and the consecutive cap from the
    same places the request flow uses, so every suggested break passes
    validate_request. Holidays span this year and the next so a late-year run can
    extend into January free days."""
    balance = remaining_balance(db, employee, "vacation", today)
    holidays = holidays_for_year(db, today.year) | holidays_for_year(db, today.year + 1)
    existing = active_full_leave_ranges(db, employee["slack_user_id"])
    cap = get_policy(db)["consecutive_limit"]["vacation"]
    return top_breaks(today, date(today.year, 12, 31), balance, holidays, existing, cap)


def open_advance(ack, body, db, today=None):
    """`/advance`: reply with the caller's top distinct vacation breaks (up to 3,
    longest-first) they can still take this year, each with a Book button — or a
    clear nothing-to-suggest note. Read-only and fast (no modal, no calendar), so
    it acks the reply directly in both run modes."""
    today = today or date.today()
    employee = get_employee(db, body["user_id"])
    if employee is None:
        ack(CONTACT_ADMIN)
        return
    breaks = _suggest_breaks(db, employee, today)
    if not breaks:
        ack(ADVANCE_NOTHING)
        return
    ack(
        {
            "response_type": "ephemeral",
            "text": "🌴 Your break options this year",
            "blocks": build_advance_blocks(breaks),
        }
    )


def open_book_modal(ack, body, client, db, today=None):
    """/advance Book button: open the apply modal pre-filled with the chosen
    break's vacation dates (`start|end` from the button value). No new write path
    — submitting runs the normal request flow, where validate_request is the
    safety net for a break gone stale (e.g. balance changed) by submit time."""
    ack()
    today = today or date.today()
    employee = get_employee(db, body["user"]["id"])
    if employee is None:
        return
    start, end = body["actions"][0]["value"].split("|")
    balances = remaining_balances(db, employee, today)
    client.views_open(
        trigger_id=body["trigger_id"],
        view=build_leave_modal(
            balances, prefill={"leave_type": "vacation", "start": start, "end": end}
        ),
    )


def open_group_picker(ack, body, client):
    """/advance 'Plan a group break' button: open the people-picker modal. Fast
    (modal open only), so it runs synchronously in both run modes."""
    ack()
    client.views_open(trigger_id=body["trigger_id"], view=build_group_picker_modal())


def _gather_member(db, employee, today, holidays, cap):
    return Member(
        remaining_balance(db, employee, "vacation", today),
        cap,
        active_full_leave_ranges(db, employee["slack_user_id"]),
    )


def _render_group_result(window):
    start, end = window
    days = (end - start).days + 1
    return (
        f"👥 Longest window you can all be off together: {start.isoformat()} to "
        f"{end.isoformat()} ({days} days). Everyone books their own leave for these dates."
    )


def submit_group_break_apply(body, view, client, db, today=None):
    """Post-ack work: gather the caller + picked people, find the longest window
    they can all be off together, and DM the caller the shareable result with a
    Book-mine button. Reveals only the window — never an individual's balance or
    whose constraint bound it."""
    today = today or date.today()
    caller_id = body["user"]["id"]
    caller = get_employee(db, caller_id)
    if caller is None:
        return
    picked = view["state"]["values"]["people"]["value"].get("selected_users") or []
    holidays = holidays_for_year(db, today.year) | holidays_for_year(db, today.year + 1)
    cap = get_policy(db)["consecutive_limit"]["vacation"]
    members = []
    for uid in dict.fromkeys([caller_id] + picked):  # caller first, de-duplicated
        emp = get_employee(db, uid)
        if emp is not None:
            members.append(_gather_member(db, emp, today, holidays, cap))
    window = group_break(today, date(today.year, 12, 31), holidays, members)
    if window is None:
        _notify(client, caller_id, GROUP_NO_WINDOW)
        return
    text = _render_group_result(window)
    client.chat_postMessage(
        channel=caller_id, text=text, blocks=build_group_result_blocks(window, text)
    )


def submit_group_break(ack, body, view, client, db, today=None):
    """Synchronous submit (Socket Mode / tests): ack to close the modal, then
    compute + DM the shared window."""
    ack()
    submit_group_break_apply(body, view, client, db, today)


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


def _self_approves(employee):
    """No separate approver — top of chain. True when the employee has no manager,
    or is listed as their own manager (which an admin can set via Manage employees).
    Either way their requests auto-approve rather than routing a ticket to anyone."""
    return employee["manager_id"] is None or employee["manager_id"] == employee["slack_user_id"]


def _coverage_warning(db, employee, start, end):
    """Coverage Radar: if any of the requester's peers (employees sharing their
    manager, the requester excluded) already have pending/approved leave over
    [start, end], return a heads-up warning string for the ticket; else None.
    A manager whose only report is the requester yields no peers, so no warning."""
    peers = []
    for p in list_reports(db, employee["manager_id"]):
        if p["slack_user_id"] == employee["slack_user_id"]:
            continue
        name = p.get("real_name", p["slack_user_id"])
        peers += [
            (name, s, e, status)
            for s, e, status in pending_approved_intervals(db, p["slack_user_id"])
        ]
    overlap = peer_overlap(start, end, peers)
    return format_coverage_warning(overlap) if overlap else None


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

    # Top of chain (no manager, or their own manager): auto-approve.
    if _self_approves(employee):
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
    coverage_warning = _coverage_warning(db, employee, start, end)
    blocks = build_ticket(
        request_id,
        employee["real_name"],
        leave_type,
        start,
        end,
        reason,
        remaining,
        half,
        coverage_warning=coverage_warning,
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
        if not _self_approves(employee):  # only FYI a real, distinct manager
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
