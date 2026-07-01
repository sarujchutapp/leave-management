"""Slack handler logic, written as plain functions so tests can pass fakes.

app.py registers these on the Bolt app, supplying a real DB connection; Bolt
injects ack/body/view/client/logger by parameter name.
"""

import json
from datetime import date, timedelta

from leave.blocks import (
    CARRY_OVER_TOGGLE_ACTION,
    CLEAR_CONFIRM_WORD,
    CONSECUTIVE_TOGGLE_ACTION,
    HOLIDAYS_ACTION_SELECT,
    MANAGE_ACTION_SELECT,
    REPORT_TYPE_ACTION,
    build_advance_modal,
    build_burnout_board_modal,
    build_burnout_loading_modal,
    build_cancel_modal,
    build_group_picker_modal,
    build_group_result_blocks,
    build_carry_over_modal,
    build_clear_modal,
    build_control_menu,
    build_holidays_modal,
    build_decision_notice,
    build_decline_modal,
    build_leave_limits_modal,
    build_leave_modal,
    build_manage_employees_modal,
    build_report_modal,
    build_settings_view,
    build_ticket,
    format_period,
    mark_row_nudged,
)
from leave.board import update_board
from leave.calendar_client import color_id_for
from leave.db import employee_with_name, get_employee, list_reports
from leave.policy import DEFAULT_POLICY, get_policy, set_policy
from leave.report import (
    build_burnout_csv,
    build_history_csv,
    build_report_csv,
    ranked_burnout_signals,
)
from leave.seed import delete_employee, set_allowance_override, upsert_employee
from leave.coverage import format_coverage_warning, peer_overlap
from leave.holidays import (
    HolidayImportError,
    all_holidays,
    apply_holidays,
    delete_holiday,
    holidays_between,
    parse_holiday_text,
)
from leave.leave_year import current_period, leave_period, reset_transition
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
    early_return,
    early_return_reclaim_days,
    get_request,
    half_day_dates,
    is_early_returnable,
    is_in_progress,
    pending_days,
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
    "have days awaiting approval, or have no open stretch left this year."
)
GROUP_NO_WINDOW = (
    "No window found where everyone can be off together in the rest of the year — "
    "try a smaller group or different people."
)
GROUP_HAS_BOT = "Pick real people — apps/bots can't take leave."


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


# Block_ids of the per-type allowance inputs in the leave-limits modal (also the keys
# of the parsed values). The vacation consecutive limit is a separate, optional input.
_ALLOWANCE_FIELDS = ("sick", "vacation", "personal")


def _checkbox_on(values, block_id, action_id):
    """Whether a single-option checkbox in a modal is ticked."""
    selected = values.get(block_id, {}).get(action_id, {}).get("selected_options") or []
    return len(selected) > 0


def open_leave_limits(ack, body, client, db, admin_ids):
    """Leave limits button: re-checks admin, then pushes the modal pre-filled from
    the current central policy."""
    ack()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    client.views_push(trigger_id=body["trigger_id"], view=build_leave_limits_modal(get_policy(db)))


def update_leave_limits_modal(ack, body, client, db, admin_ids):
    """Enforce-consecutive-limit checkbox toggled: re-render the modal in place so the
    number field shows only when the cap is enforced. Rebuilds from the stored policy
    (unsaved edits revert — the modal is touched rarely); enabling from off seeds the
    number with the shipped default."""
    ack()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    enforce = bool(body["actions"][0].get("selected_options"))
    policy = get_policy(db)
    value = DEFAULT_POLICY["consecutive_limit"]["vacation"] if enforce else None
    if not enforce or policy["consecutive_limit"]["vacation"] is None:
        policy = {**policy, "consecutive_limit": {"vacation": value}}
    client.views_update(view_id=body["view"]["id"], view=build_leave_limits_modal(policy))


def _parse_int(raw):
    """(value, None) for a non-negative whole number, else (None, error)."""
    try:
        n = int(raw)
    except (ValueError, TypeError):
        return None, "Enter a whole number."
    if n < 0:
        return None, "Must be zero or greater."
    return n, None


def _parse_leave_limits(view, db):
    """(allowances, consecutive_or_None, errors) for the leave-limits modal. Allowances
    are required non-negative whole numbers; the consecutive limit is parsed only when
    enforced (else None). Enforces Vacation allowance <= Max total (which lives in the
    Carry-over modal, so it's checked here)."""
    values = view["state"]["values"]
    parsed, errors = {}, {}
    for field in _ALLOWANCE_FIELDS:
        n, err = _parse_int(values[field]["value"]["value"])
        if err:
            errors[field] = err
        else:
            parsed[field] = n
    consecutive = None
    if _checkbox_on(values, "enforce_consecutive", CONSECUTIVE_TOGGLE_ACTION):
        consecutive, err = _parse_int(values["consecutive_limit"]["value"]["value"])
        if err:
            errors["consecutive_limit"] = err
    max_total = get_policy(db)["max_total"]["vacation"]
    if "vacation" in parsed and parsed["vacation"] > max_total:
        errors["vacation"] = (
            f"Vacation allowance can't exceed Max total ({max_total}). "
            "Raise Max total in Carry-over first."
        )
    return parsed, consecutive, errors


def submit_leave_limits_ack(ack, body, view, db, admin_ids):
    """Ack phase (under 3s): re-check admin and validate, closing the modal or returning
    inline errors. The write + any carry-in recompute run post-ack."""
    if not is_admin(body["user"]["id"], admin_ids):
        ack()
        return
    _, _, errors = _parse_leave_limits(view, db)
    if errors:
        ack(response_action="errors", errors=errors)
    else:
        ack(response_action="clear")  # close the whole modal stack on success


def submit_leave_limits_apply(body, view, db, client, admin_ids, today=None):
    """Post-ack work: write the new allowances + consecutive limit, preserving the
    carry-over caps. The base vacation allowance feeds carry_in, so when it changes we
    rebuild every employee's stored carry_in (issue #8) — skipped otherwise. Re-checks
    admin + validity because Lambda lazy listeners fire regardless of the ack result."""
    today = today or date.today()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    parsed, consecutive, errors = _parse_leave_limits(view, db)
    if errors:
        return
    policy = get_policy(db)
    vacation_changed = parsed["vacation"] != policy["allowances"]["vacation"]
    set_policy(
        db,
        allowances={
            "sick": parsed["sick"],
            "vacation": parsed["vacation"],
            "personal": parsed["personal"],
        },
        max_carry_over=policy["max_carry_over"],
        max_total=policy["max_total"],
        consecutive_limit={"vacation": consecutive},
    )
    msg = (
        f"✅ Leave limits updated — sick {parsed['sick']}, vacation {parsed['vacation']}, "
        f"personal {parsed['personal']}, consecutive limit "
        f"{consecutive if consecutive is not None else 'off'}."
    )
    if vacation_changed:
        count = recompute_all_carry_in(db, today.year)
        msg += f" Carry-in recomputed for {count} employee(s)."
    _notify(client, body["user"]["id"], msg)


def submit_leave_limits(ack, body, view, client, db, admin_ids, today=None):
    """Synchronous submit (Socket Mode / tests): validate-and-ack, then apply."""
    submit_leave_limits_ack(ack, body, view, db, admin_ids)
    submit_leave_limits_apply(body, view, db, client, admin_ids, today)



def open_carry_over(ack, body, client, db, admin_ids, today=None):
    """Carry-over button: re-checks admin, then pushes the modal pre-filled with the
    current vacation carry-over caps and reset date."""
    ack()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    today = today or date.today()
    client.views_push(
        trigger_id=body["trigger_id"], view=build_carry_over_modal(get_policy(db), today)
    )


def update_carry_over_modal(ack, body, client, db, admin_ids, today=None):
    """Enable-carry-over checkbox toggled: re-render in place so the Max carry over field
    shows only when carry-over is on. Rebuilds from the stored policy (unsaved edits
    revert — rarely touched); enabling from off seeds the field with the shipped default."""
    ack()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    today = today or date.today()
    enabled = bool(body["actions"][0].get("selected_options"))
    policy = get_policy(db)
    current = policy["max_carry_over"]["vacation"]
    if enabled:
        value = current if current > 0 else DEFAULT_POLICY["max_carry_over"]["vacation"]
    else:
        value = 0
    policy = {**policy, "max_carry_over": {"vacation": value}}
    client.views_update(view_id=body["view"]["id"], view=build_carry_over_modal(policy, today))


def _parse_carry_over(view, db):
    """(parsed, errors) for the carry-over modal. Max total is a required non-negative
    whole number; max carry over is parsed only when "Enable carry-over" is ticked,
    else it is 0 (carry-over disabled — nothing rolls over). Enforces the invariants
    Max total >= vacation allowance and Max carry over <= Max total."""
    values = view["state"]["values"]
    policy = get_policy(db)
    parsed, errors = {}, {}
    max_total, err = _parse_int(values["max_total"]["value"]["value"])
    if err:
        errors["max_total"] = err
    else:
        parsed["max_total"] = max_total
    if _checkbox_on(values, "enable_carry_over", CARRY_OVER_TOGGLE_ACTION):
        mco, err = _parse_int(values["max_carry_over"]["value"]["value"])
        if err:
            errors["max_carry_over"] = err
        else:
            parsed["max_carry_over"] = mco
    else:
        parsed["max_carry_over"] = 0
    # Reset date (month/day; year ignored). Absent from older payloads -> keep current.
    picked = values.get("reset_date", {}).get("value", {}).get("selected_date")
    if picked:
        d = date.fromisoformat(picked)
        parsed["reset_month"], parsed["reset_day"] = d.month, d.day
    else:
        parsed["reset_month"], parsed["reset_day"] = policy["reset_month"], policy["reset_day"]
    allowance = policy["allowances"]["vacation"]
    if "max_total" in parsed and parsed["max_total"] < allowance:
        errors["max_total"] = f"Max total can't be below the vacation allowance ({allowance})."
    elif "max_total" in parsed and "max_carry_over" in parsed and parsed["max_carry_over"] > parsed["max_total"]:
        errors["max_carry_over"] = f"Max carry over can't exceed Max total ({parsed['max_total']})."
    return parsed, errors


def _reset_date_change(policy, parsed, today):
    """The forward-only move to the submitted reset date. Returns `(set_policy kwargs,
    admin note)` — empty kwargs and no note when the date is unchanged. The current
    period keeps its start (pinned), so no past period is recomputed and balances don't
    shift; only when it next resets moves — a shorter stub or a longer stretch."""
    new_month, new_day = parsed["reset_month"], parsed["reset_day"]
    cur_start, cur_end = current_period(
        today,
        policy["reset_month"],
        policy["reset_day"],
        policy["reset_anchor"],
        policy["reset_period_start"],
    )
    new_anchor, kind = reset_transition(today, cur_end, new_month, new_day)
    if kind == "unchanged":
        return {}, None
    kwargs = {
        "reset_month": new_month,
        "reset_day": new_day,
        "reset_anchor": new_anchor,
        "reset_period_start": cur_start,
    }
    shape = "shorter (a stub)" if kind == "stub" else "longer (a stretch)"
    note = (
        f"📅 Leave-year reset date updated. The current period is now {shape} — it ends "
        f"{(new_anchor - timedelta(days=1)).isoformat()}, then quota resets. "
        "Existing balances don't shift."
    )
    return kwargs, note


def submit_carry_over_ack(ack, body, view, db, admin_ids, client=None, today=None):
    """Ack phase (under 3s): re-check admin, validate, write the new caps, and apply any
    forward-only reset-date change (store + admin note, no recompute). Returns True when
    applied, so the caller knows to run the post-ack carry-in recompute for the caps."""
    if not is_admin(body["user"]["id"], admin_ids):
        ack()
        return False
    parsed, errors = _parse_carry_over(view, db)
    if errors:
        ack(response_action="errors", errors=errors)
        return False
    ack(response_action="clear")  # close the whole modal stack on success
    today = today or date.today()
    policy = get_policy(db)
    reset_kwargs, note = _reset_date_change(policy, parsed, today)
    set_policy(
        db,
        allowances=policy["allowances"],
        max_carry_over={"vacation": parsed["max_carry_over"]},
        max_total={"vacation": parsed["max_total"]},
        consecutive_limit=policy["consecutive_limit"],
        **reset_kwargs,
    )
    if note and client is not None:
        _notify(client, body["user"]["id"], note)
    return True


def submit_carry_over_apply(body, view, db, client, admin_ids, today=None):
    """Post-ack work: rebuild every employee's stored carry_in under the new caps,
    then DM the admin the result. Re-checks admin + validity because Lambda lazy
    listeners fire regardless of the ack result; an invalid/non-admin submission is
    dropped (no recompute)."""
    today = today or date.today()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    _, errors = _parse_carry_over(view, db)
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
    if submit_carry_over_ack(ack, body, view, db, admin_ids, client, today):
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
    count = clear_all_requests(db, calendar, sheets, today, client=client)
    _notify(
        client,
        body["user"]["id"],
        f"🧹 Cleared {count} leave request(s), removed their calendar events, and reset the board.",
    )


def submit_clear(ack, body, view, db, calendar, sheets, client, admin_ids, today=None):
    """Synchronous submit (Socket Mode / tests): ack-with-confirmation, then wipe."""
    if submit_clear_ack(ack, body, view, admin_ids):
        submit_clear_apply(body, view, db, calendar, sheets, client, admin_ids, today)


def _upcoming_holidays(db, today):
    """Holidays dated today or later — the Remove picker's scope. Holidays accumulate
    year over year, so scoping to current-and-future keeps the dropdown permanently
    under Slack's 100-option static_select limit (a past holiday never affects future
    leave counting, and a re-import can overwrite anything)."""
    return [h for h in all_holidays(db) if h[0] >= today]


def open_holidays(ack, body, client, db, admin_ids, today=None):
    """Holidays button: re-checks admin, then pushes the add/remove modal, the
    remove dropdown pre-filled with the current (today-onward) holidays."""
    ack()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    today = today or date.today()
    client.views_push(
        trigger_id=body["trigger_id"], view=build_holidays_modal(_upcoming_holidays(db, today))
    )


def _holiday_action(view):
    return (
        view["state"]["values"]
        .get("holiday_action", {})
        .get(HOLIDAYS_ACTION_SELECT, {})
        .get("selected_option", {})
        .get("value")
        or "add"
    )


def _parse_holiday_submission(view):
    """(date_or_None, label_or_None, remove_iso_or_None) from the holidays modal."""
    values = view["state"]["values"]
    date_raw = values.get("holiday_date", {}).get("value", {}).get("selected_date")
    d = _to_gregorian(date.fromisoformat(date_raw)) if date_raw else None
    label = (values.get("holiday_label", {}).get("value", {}).get("value") or "").strip() or None
    remove_opt = values.get("holiday_remove", {}).get("value", {}).get("selected_option")
    remove = remove_opt.get("value") if remove_opt else None
    return d, label, remove


def _import_text(view):
    """The pasted holiday text from the import field, or "" when absent."""
    return (
        view["state"]["values"].get("holiday_import", {}).get("value", {}).get("value") or ""
    )


def update_holidays_modal(ack, body, client, db, admin_ids, today=None):
    """Action select changed: re-render the modal in place so only the chosen mode's
    fields show (Add → date + label, Remove → the current-holidays dropdown)."""
    ack()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    today = today or date.today()
    action = body["actions"][0]["selected_option"]["value"]
    client.views_update(
        view_id=body["view"]["id"],
        view=build_holidays_modal(_upcoming_holidays(db, today), action),
    )


def submit_holidays_ack(ack, body, view, admin_ids):
    """Ack phase (under 3s): re-check admin and validate the chosen mode's fields — Add
    needs a date + label, Remove needs a holiday picked. Returns True when valid so the
    caller runs the calendar+store change post-ack."""
    if not is_admin(body["user"]["id"], admin_ids):
        ack()
        return False
    d, label, remove = _parse_holiday_submission(view)
    if _holiday_action(view) == "remove":
        if remove:
            ack(response_action="clear")  # close the whole modal stack on success
            return True
        ack(response_action="errors", errors={"holiday_remove": "Pick a holiday to remove."})
        return False
    if _holiday_action(view) == "import":
        try:
            parse_holiday_text(_import_text(view))
        except HolidayImportError as e:
            ack(response_action="errors", errors={"holiday_import": "\n".join(e.errors)})
            return False
        ack(response_action="clear")
        return True
    errors = {}
    if not d:
        errors["holiday_date"] = "Pick the holiday's date."
    if not label:
        errors["holiday_label"] = "Add a label for the holiday."
    if errors:
        ack(response_action="errors", errors=errors)
        return False
    ack(response_action="clear")  # close the whole modal stack on success
    return True


def submit_holidays_apply(body, view, db, calendar, client, admin_ids):
    """Post-ack work: apply the add (create the calendar event + store) or the remove
    (delete the event + entry), then DM the admin. Re-checks admin + validity because
    Lambda lazy listeners fire regardless of the ack result."""
    if not is_admin(body["user"]["id"], admin_ids):
        return
    d, label, remove = _parse_holiday_submission(view)
    user_id = body["user"]["id"]
    if _holiday_action(view) == "remove":
        if not remove:
            return
        removed = delete_holiday(db, date.fromisoformat(remove))
        if removed and removed.get("calendar_event_id"):
            calendar.delete_event(removed["calendar_event_id"])
        _notify(client, user_id, f"🗑️ Removed holiday {remove}.")
    elif _holiday_action(view) == "import":
        try:
            rows = parse_holiday_text(_import_text(view))
        except HolidayImportError:
            return  # invalid paste already surfaced in the ack; import nothing
        apply_holidays(db, calendar, rows)
        _notify(client, user_id, f"✅ Imported {len(rows)} holidays.")
    elif d and label:
        apply_holidays(db, calendar, [(d, label)])
        _notify(client, user_id, f"✅ Saved holiday {d.isoformat()} — {label}.")


def submit_holidays(ack, body, view, db, calendar, client, admin_ids):
    """Synchronous submit (Socket Mode / tests): ack-with-validation, then apply."""
    if submit_holidays_ack(ack, body, view, admin_ids):
        submit_holidays_apply(body, view, db, calendar, client, admin_ids)


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
    # The person picker is a Slack user-picker, so the value is selected_user.
    person = values.get("person", {}).get("value", {}).get("selected_user")
    return report_type, person


def submit_report_ack(ack, body, view, client, admin_ids):
    """Ack phase (under 3s): re-check admin and validate the choice. A history report
    needs a person picked, and not an app/bot (the user-picker can't hide bots, so it's
    rejected on submit). Returns True so the caller builds + sends."""
    if not is_admin(body["user"]["id"], admin_ids):
        ack()
        return False
    report_type, person = _report_choice(view)
    if report_type == "history":
        if not person:
            ack(response_action="errors", errors={"person": "Pick the person whose history you want."})
            return False
        if _is_bot(client, person):
            ack(response_action="errors", errors={"person": "Pick a teammate, not an app or bot."})
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
        if not person or _is_bot(client, person):
            return  # missing/bot pick already surfaced in the ack
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
    if submit_report_ack(ack, body, view, client, admin_ids):
        submit_report_apply(body, view, db, client, admin_ids, today)


_OVERRIDE_TYPES = ("sick", "vacation", "personal")


def open_manage_employees(ack, body, client, admin_ids):
    """Manage employees button: re-checks admin, then pushes the modal (Add/edit by
    default — the fields shown change with the Action select)."""
    ack()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    client.views_push(trigger_id=body["trigger_id"], view=build_manage_employees_modal())


def update_manage_modal(ack, body, client, admin_ids):
    """Action select changed: re-render the modal in place so only the chosen action's
    fields show (Add/edit → name + manager, Set override → allowances, Delete → none).
    Keeps the picked employee selected so their prefill survives the switch."""
    ack()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    action = body["actions"][0]["selected_option"]["value"]
    values = body.get("view", {}).get("state", {}).get("values", {})
    selected = _value(values, "employee").get("selected_user")
    client.views_update(
        view_id=body["view"]["id"], view=build_manage_employees_modal(action, selected_user=selected)
    )


def prefill_manage_employee(ack, body, client, db, admin_ids):
    """Employee picked: re-render the modal with that registered employee's current
    name/manager/override prefilled (blank for someone not yet in the system), keeping
    them selected. Turns "Add / edit" into real editing and a way to view current values."""
    ack()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    selected = body["actions"][0].get("selected_user")
    action = _manage_action(body["view"]["state"]["values"])
    employee = get_employee(db, selected) if selected else None
    client.views_update(
        view_id=body["view"]["id"],
        view=build_manage_employees_modal(action, selected_user=selected, employee=employee),
    )


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


def _manage_action(values):
    return values.get("action", {}).get(MANAGE_ACTION_SELECT, {}).get("selected_option", {}).get("value")


def _is_bot(client, user_id):
    """True if the Slack user is an app/bot (or Slackbot). A Slack user-picker always
    lists apps/bots and can't filter them out, so we reject one on submit instead.
    Needs the users:read scope."""
    info = client.users_info(user=user_id).get("user", {})
    return bool(info.get("is_bot") or info.get("is_app_user")) or user_id == "USLACKBOT"


EMPLOYEE_REMOVED_WITHDRAW = (
    "This request was withdrawn — the employee was removed from the leave system."
)
MANAGER_CHANGED_WITHDRAW = (
    "This request was withdrawn — the employee's manager changed; they'll re-file."
)


def _withdraw_ticket(client, request, text):
    """Replace a pending request's manager ticket so its Approve/Decline buttons vanish."""
    if request.get("ticket_ts"):
        client.chat_update(
            channel=request["ticket_channel"],
            ts=request["ticket_ts"],
            text="Request withdrawn",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
        )


def _settle_in_flight_leave(
    db, client, calendar, sheets, employee_id, withdraw_text, today, include_approved
):
    """Cancel this employee's still-open requests, cleaning up each artifact so nothing
    dangles: a pending request's manager ticket is withdrawn. When `include_approved`
    (a full removal), a future-approved request is also cancelled and its calendar event
    and board entry removed; otherwise (a manager change) approved leave is left intact,
    since it needs no further manager action. Past (taken) leave is always kept as
    history. Returns the number of pending requests withdrawn."""
    pending = 0
    for request in cancellable_requests(db, employee_id, today):
        if request["status"] == "pending":
            cancel_request(db, request["request_id"])
            pending += 1
            _withdraw_ticket(client, request, withdraw_text)
        elif include_approved and request["start_date"] > today:  # future-approved only: drop its calendar event and board entry
            cancel_request(db, request["request_id"])
            if request["calendar_event_id"]:
                calendar.delete_event(request["calendar_event_id"])
            update_board(db, client, today, sheets, remove_request_id=request["request_id"])
    return pending


def _manage_errors(values, client, db, target, action):
    """Inline-error validation shared by the ack and apply phases (empty dict = valid).
    Delete is block-and-tell (a person still managing anyone is rejected naming those
    reports); save requires a unique name + a manager, neither an app/bot."""
    if action == "delete":
        reports = [r for r in list_reports(db, target) if r["slack_user_id"] != target]
        if reports:
            names = ", ".join(sorted(r.get("real_name", r["slack_user_id"]) for r in reports))
            return {"employee": f"Still the manager of {names}. Re-assign them first, then delete."}
        return {}
    if action == "override":
        _, errors = _parse_overrides(values)
        return errors
    # save (add / edit)
    name = (_value(values, "name").get("value") or "").strip()
    manager = _value(values, "manager").get("selected_user")
    errors = {}
    if not name:
        errors["name"] = "Name is required."
    if not manager:
        errors["manager"] = "Pick a manager — the person themselves if they're top of chain."
    # Names appear on manager approval tickets, so keep them unique across employees.
    if name and employee_with_name(db, name, exclude_id=target):
        errors["name"] = "That name is already used by another employee — pick a distinct name."
    if errors:
        return errors
    # The user-picker always lists the app/Slackbot; block adding one as an employee
    # or manager (Slack gives no way to hide them from the picker itself).
    if _is_bot(client, target):
        return {"employee": "Pick a real person — that's an app/bot."}
    if manager != target and _is_bot(client, manager):
        return {"manager": "Pick a real person — that's an app/bot."}
    return {}


def submit_manage_employees_ack(ack, body, view, client, db, admin_ids):
    """Ack phase (under 3s): re-check admin and validate, returning inline errors or
    closing the modal. The work (which can make slow Slack/calendar calls when leave
    is settled) runs post-ack in submit_manage_employees_apply."""
    if not is_admin(body["user"]["id"], admin_ids):
        ack()
        return
    values = view["state"]["values"]
    target = _value(values, "employee").get("selected_user")
    action = _manage_action(values)
    errors = _manage_errors(values, client, db, target, action)
    if errors:
        ack(response_action="errors", errors=errors)
    else:
        ack(response_action="clear")  # close the whole modal stack on success


def submit_manage_employees_apply(
    body, view, client, db, admin_ids, calendar=None, sheets=None, today=None
):
    """Post-ack work: do the add/edit, override, or delete, settling in-flight leave
    when a person is removed or re-orged (ADR-0009). Re-checks admin + validity because
    Lambda lazy listeners fire regardless of the ack result; an invalid submission is
    dropped (the user already saw the error)."""
    today = today or date.today()
    if not is_admin(body["user"]["id"], admin_ids):
        return
    values = view["state"]["values"]
    target = _value(values, "employee").get("selected_user")
    action = _manage_action(values)
    if _manage_errors(values, client, db, target, action):
        return

    if action == "delete":
        _settle_in_flight_leave(
            db, client, calendar, sheets, target, EMPLOYEE_REMOVED_WITHDRAW, today,
            include_approved=True,
        )
        delete_employee(db, target)
        _notify(client, body["user"]["id"], f"🗑️ Removed <@{target}> from the leave system.")
        return

    if action == "override":
        overrides, _ = _parse_overrides(values)
        set_allowance_override(db, target, overrides)
        what = "set" if overrides else "cleared"
        _notify(client, body["user"]["id"], f"✅ Allowance override {what} for <@{target}>.")
        return

    # save (add / edit): name + manager. Manager = the person themselves marks them top
    # of chain (their leave auto-approves). A manager change strands the employee's
    # pending tickets (they sit in the old manager's DM, but the approver check reads
    # the new manager), so settle them and ask the employee to re-file; approved leave
    # is unaffected. Detected before the write so we can compare against the stored
    # manager.
    name = (_value(values, "name").get("value") or "").strip()
    manager = _value(values, "manager").get("selected_user")
    existing = get_employee(db, target)
    manager_changed = existing is not None and existing["manager_id"] != manager
    upsert_employee(db, target, name, manager, allowances=None)
    _notify(client, body["user"]["id"], f"✅ Saved {name} (<@{target}>).")
    if manager_changed:
        withdrawn = _settle_in_flight_leave(
            db, client, calendar, sheets, target, MANAGER_CHANGED_WITHDRAW, today,
            include_approved=False,
        )
        if withdrawn:
            _notify(
                client,
                target,
                f"Your manager is now <@{manager}>. {withdrawn} pending request(s) were "
                "withdrawn — please re-file them so they reach the right approver.",
            )


def submit_manage_employees(ack, body, view, client, db, admin_ids, calendar=None, sheets=None, today=None):
    """Synchronous submit (Socket Mode / tests): validate-and-ack, then apply."""
    submit_manage_employees_ack(ack, body, view, client, db, admin_ids)
    submit_manage_employees_apply(body, view, client, db, admin_ids, calendar, sheets, today)


def open_leave_modal(ack, body, client, db, today=None):
    today = today or date.today()
    employee = get_employee(db, body["user_id"])
    if employee is None:
        ack(CONTACT_ADMIN)
        return
    ack()
    balances = remaining_balances(db, employee, today)
    client.views_open(trigger_id=body["trigger_id"], view=build_leave_modal(balances))


def _free_vacation_balance(db, employee, today):
    """Vacation days truly free to book: remaining (approved-only) minus pending.
    Pending counts as reserved, so the optimizer never suggests over what's already in
    flight — the same free notion validate_request now gates on (ADR-0010)."""
    return remaining_balance(db, employee, "vacation", today) - pending_days(
        db, employee["slack_user_id"], "vacation", today
    )


def _optimizer_horizon(db, today):
    """The optimizer's horizon for `today`: the last day of the current leave period
    (the day before the next reset — 31 Dec by default) and the holidays across the
    window up to the reset. A suggested break stays within the current leave year, so
    it resets its quota fresh next period; the window may span two calendar years."""
    policy = get_policy(db)
    _, period_end = leave_period(today, policy["reset_month"], policy["reset_day"])
    last_day = period_end - timedelta(days=1)
    return last_day, holidays_between(db, today, period_end)


def _suggest_breaks(db, employee, today):
    """Gather the optimizer's inputs from the db and return the caller's top
    distinct bookable vacation breaks in the current leave period (longest-first, up
    to 3). Sources balance, holidays, existing full-day leave and the consecutive cap
    from the same places the request flow uses, so every suggested break passes
    validate_request. Breaks are bounded by the next reset, not 31 Dec."""
    uid = employee["slack_user_id"]
    balance = _free_vacation_balance(db, employee, today)
    last_day, holidays = _optimizer_horizon(db, today)
    existing = active_full_leave_ranges(db, uid)
    blocked = half_day_dates(db, uid)
    cap = get_policy(db)["consecutive_limit"]["vacation"]
    return top_breaks(today, last_day, balance, holidays, existing, cap, blocked_dates=blocked)


def open_advance(ack, body, client, db, today=None):
    """`/advance`: open a modal with the caller's top distinct vacation breaks (up to
    3, longest-first) they can still take this year, each with a Book button and a
    group-break button — or a clear nothing-to-suggest note. Read-only and fast (one
    keyed modal open, no calendar/board work), so it runs synchronously in both run
    modes; an unregistered caller just gets an ephemeral note."""
    today = today or date.today()
    employee = get_employee(db, body["user_id"])
    if employee is None:
        ack(CONTACT_ADMIN)
        return
    breaks = _suggest_breaks(db, employee, today)
    ack()
    client.views_open(
        trigger_id=body["trigger_id"], view=build_advance_modal(breaks, ADVANCE_NOTHING)
    )


def open_book_modal(ack, body, client, db, today=None):
    """/advance Book button: open the apply modal pre-filled with the chosen
    break's vacation dates (`start|end` from the button value). No new write path
    — submitting runs the normal request flow, where validate_request is the
    safety net for a break gone stale (e.g. balance changed) by submit time. Pushed
    onto the stack when clicked inside the /advance modal (body carries a `view`),
    opened as a fresh root from the group-break DM message (book-one-and-done: the
    whole stack closes on submit)."""
    ack()
    today = today or date.today()
    employee = get_employee(db, body["user"]["id"])
    if employee is None:
        return
    start, end = body["actions"][0]["value"].split("|")
    balances = remaining_balances(db, employee, today)
    show = client.views_push if body.get("view") else client.views_open
    show(
        trigger_id=body["trigger_id"],
        view=build_leave_modal(
            balances, prefill={"leave_type": "vacation", "start": start, "end": end}
        ),
    )


def open_group_picker(ack, body, client):
    """/advance 'Plan a group break' button: open the people-picker modal. The
    button lives inside the /advance modal, so the picker is pushed onto the stack —
    views_open is ignored mid-modal. Fast (modal only), so it runs synchronously."""
    ack()
    show = client.views_push if body.get("view") else client.views_open
    show(trigger_id=body["trigger_id"], view=build_group_picker_modal())


def _gather_member(db, employee, today, holidays, cap):
    uid = employee["slack_user_id"]
    return Member(
        _free_vacation_balance(db, employee, today),
        cap,
        active_full_leave_ranges(db, uid),
        half_day_dates(db, uid),
    )


def _render_group_result(window):
    start, end = window
    days = (end - start).days + 1
    return (
        f"👥 Longest window you can all be off together: {start.isoformat()} to "
        f"{end.isoformat()} ({days} days). Everyone books their own leave for these dates."
    )


def _picked_users(view):
    return view["state"]["values"]["people"]["value"].get("selected_users") or []


def _has_bot_pick(client, view):
    """Whether any picked teammate is an app/bot. The user-picker can't hide them
    (see _is_bot), so a group submit with one is rejected on submit."""
    return any(_is_bot(client, uid) for uid in _picked_users(view))


def submit_group_break_apply(body, view, client, db, today=None):
    """Post-ack work: gather the caller + picked people, find the longest window
    they can all be off together, and DM the caller the shareable result with a
    Book-mine button. Reveals only the window — never an individual's balance or
    whose constraint bound it. Bails on a bot pick (rejected in the ack with an
    inline error; Lambda lazy listeners fire regardless of the ack, so re-check)."""
    if _has_bot_pick(client, view):
        return
    today = today or date.today()
    caller_id = body["user"]["id"]
    caller = get_employee(db, caller_id)
    if caller is None:
        return
    picked = _picked_users(view)
    last_day, holidays = _optimizer_horizon(db, today)
    cap = get_policy(db)["consecutive_limit"]["vacation"]
    members = []
    for uid in dict.fromkeys([caller_id] + picked):  # caller first, de-duplicated
        emp = get_employee(db, uid)
        if emp is not None:
            members.append(_gather_member(db, emp, today, holidays, cap))
    window = group_break(today, last_day, holidays, members)
    if window is None:
        _notify(client, caller_id, GROUP_NO_WINDOW)
        return
    text = _render_group_result(window)
    client.chat_postMessage(
        channel=caller_id, text=text, blocks=build_group_result_blocks(window, text)
    )


def submit_group_break_ack(ack, view, client):
    """Ack phase (Lambda): reject a bot pick with an inline error so the picker stays
    open, else ack to close. The lazy apply re-checks and bails (lazy listeners fire
    regardless of the ack)."""
    if _has_bot_pick(client, view):
        ack(response_action="errors", errors={"people": GROUP_HAS_BOT})
    else:
        ack()


def submit_group_break(ack, body, view, client, db, today=None):
    """Synchronous submit (Socket Mode / tests): reject a bot pick with an inline
    error, else ack to close the modal and compute + DM the shared window."""
    if _has_bot_pick(client, view):
        ack(response_action="errors", errors={"people": GROUP_HAS_BOT})
        return
    ack()
    submit_group_break_apply(body, view, client, db, today)


NOT_A_MANAGER = "You don't manage anyone, so there's no burnout board to show."


def _direct_reports(db, manager_id):
    """The caller's direct reports — employees whose manager is the caller, the
    caller themselves excluded (a self-managed top-of-chain person doesn't report
    to themselves). Reserved/config items carry no manager_id, so they never match."""
    return [r for r in list_reports(db, manager_id) if r["slack_user_id"] != manager_id]


def _board_external_id(body):
    """A deterministic handle for the board modal so the post-ack views_update finds
    the loading view opened in the ack window (the trigger_id is unique per click)."""
    return f"burnout-{body['trigger_id']}"


def open_burnout_ack(ack, body, client, db):
    """`/burnout` ack phase (under 3s): a quick manager gate via one employees scan.
    A caller who manages no one gets a clear note; a manager gets an instant loading
    modal on the trigger_id, filled in post-ack (the board reads several records,
    past Slack's 3s window — so it can't be built here)."""
    if not _direct_reports(db, body["user_id"]):
        ack(NOT_A_MANAGER)
        return
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view=build_burnout_loading_modal(_board_external_id(body)),
    )


def open_burnout_apply(body, db, client, today=None):
    """Post-ack work: rank the caller's direct reports by burnout risk and swap the
    loading modal for the board (by the external_id opened in the ack). Scoped
    strictly to the caller's own reports (the privacy guardrail); re-reads them
    because Lambda lazy listeners fire regardless of the ack, so a caller who manages
    no one updates nothing (they opened no modal)."""
    today = today or date.today()
    reports = _direct_reports(db, body["user_id"])
    if not reports:
        return
    signals = ranked_burnout_signals(db, reports, today)
    external_id = _board_external_id(body)
    client.views_update(
        external_id=external_id,
        view=build_burnout_board_modal(signals, external_id, _avatar_urls(client, signals)),
    )


def _avatar_urls(client, signals):
    """Each person's Slack profile thumbnail, fetched live via users.info (needs
    only users:read — nothing is stored). A missing/unavailable picture is simply
    omitted, so the row just shows no avatar."""
    urls = {}
    for s in signals:
        profile = client.users_info(user=s.user_id).get("user", {}).get("profile", {})
        if profile.get("image_72"):
            urls[s.user_id] = profile["image_72"]
    return urls


def open_burnout(ack, body, db, client, today=None):
    """Synchronous `/burnout` (Socket Mode / tests): manager-gate-and-ack (opening
    the loading modal), then build + update the board."""
    open_burnout_ack(ack, body, client, db)
    open_burnout_apply(body, db, client, today)


def refresh_burnout(ack, body, client, db, today=None):
    """`/burnout` Refresh button: rebuild the board in place (it's a live snapshot).
    Acks at once, then re-reads the caller's direct reports and updates the open
    modal by its view id — post-ack, like opening it."""
    ack()
    today = today or date.today()
    reports = _direct_reports(db, body["user"]["id"])
    signals = ranked_burnout_signals(db, reports, today) if reports else []
    client.views_update(
        view_id=body["view"]["id"],
        view=build_burnout_board_modal(signals, avatars=_avatar_urls(client, signals)),
    )


def _nudge_message(stretch, expiring):
    """The supportive, bot-voiced wellbeing DM: names the reason (the no-break
    stretch, plus expiring vacation when relevant) and points to /advance to plan a
    break. Reads as care, not surveillance — never punitive, and it books nothing."""
    msg = (
        f"Hi! 🌿 Just a friendly wellbeing check-in — it's been *{stretch} days* since "
        "your last time off."
    )
    if expiring:
        msg += f" You also have *{expiring}* vacation day(s) that expire when your leave year resets."
    msg += (
        " Taking a break is good for you. No pressure — but if you'd like to plan one, "
        "`/advance` can suggest the best windows. 🌴"
    )
    return msg


def handle_nudge(ack, body, client):
    """`/burnout` Nudge button: the bot DMs the at-risk report a supportive,
    wellbeing-framed message citing the reason the manager saw (carried in the
    button value), then flips that row's button to '✓ Nudged' in the board modal as
    the manager's confirmation. Bot-voiced — it never impersonates the manager — and
    it books or modifies nothing. Sent post-ack, so the click acks at once."""
    ack()
    value = body["actions"][0]["value"]
    payload = json.loads(value)
    _notify(client, payload["user_id"], _nudge_message(payload["stretch"], payload.get("expiring", 0)))
    view = body["view"]
    client.views_update(view_id=view["id"], view=mark_row_nudged(view, value))


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
    is tinted with the employee's stable colour so the calendar is readable per person.
    Returns False without creating the event if the request was already decided by a
    concurrent handler (the pending->approved transition is atomic), so the caller
    skips the rest of the approval side effects."""
    if not approve_request(db, request_id):
        return False
    summary = f"{employee['real_name']} — {leave_type}"
    if half:
        summary += f" ({half})"
    color_id = color_id_for(employee["slack_user_id"])
    event_id = calendar.create_event(summary, start, end, color_id)
    set_calendar_event_id(db, request_id, event_id)
    return True


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
        if not _finalize_approval(db, calendar, request_id, employee, leave_type, start, end, half):
            return
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


def _close_dead_ticket(client, channel, ts):
    """A decision was attempted on a request whose row is gone — Clear wiped it, or
    the employee was removed. Replace the ticket so its buttons vanish."""
    client.chat_update(
        channel=channel,
        ts=ts,
        text="No longer available",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "This request is no longer available — no action taken.",
                },
            }
        ],
    )


def handle_approve(ack, body, client, db, calendar, sheets=None, today=None):
    ack()
    today = today or date.today()
    request_id = body["actions"][0]["value"]
    request = get_request(db, request_id)
    if request is None:
        _close_dead_ticket(client, body["channel"]["id"], body["message"]["ts"])
        return
    employee = get_employee(db, request["employee_id"])
    if employee is None:
        _close_dead_ticket(client, body["channel"]["id"], body["message"]["ts"])
        return

    if body["user"]["id"] != employee["manager_id"]:
        _notify(client, body["user"]["id"], NOT_APPROVER)
        return
    if request["status"] != "pending":
        _close_stale_ticket(client, body["channel"]["id"], body["message"]["ts"], request)
        return

    if not _finalize_approval(
        db,
        calendar,
        request_id,
        employee,
        request["leave_type"],
        request["start_date"],
        request["end_date"],
        request.get("half"),
    ):
        # A concurrent approve already won the transition and did the side effects.
        return
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
    if request is None:
        _close_dead_ticket(client, body["channel"]["id"], body["message"]["ts"])
        return
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
    if request is None:
        _close_dead_ticket(client, meta["channel"], meta["ts"])
        return
    employee = get_employee(db, request["employee_id"])
    if employee is None:
        _close_dead_ticket(client, meta["channel"], meta["ts"])
        return
    if body["user"]["id"] != employee["manager_id"]:
        return
    if request["status"] != "pending":
        _close_stale_ticket(client, meta["channel"], meta["ts"], request)
        return

    if not decline_request(db, request_id, reason):
        # A concurrent decision already moved this request; don't notify twice.
        return
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
    client.views_open(trigger_id=body["trigger_id"], view=build_cancel_modal(rows, today))


def _early_return(db, calendar, client, sheets, request, today):
    """Cancel an in-progress leave as an early return: shorten it to end today (it
    stays approved — days through today stay taken; the tail refunds via the derived
    balance), re-date its calendar event to [start, today], update the board entry,
    then DM the employee and FYI a distinct manager.

    Guarded twice: a leave with nothing to give back (ends today, tail all
    weekend/holiday, or a half-day) isn't returnable, and the shorten itself is a
    conditional write — so a racing cancel or a double-submit reports it didn't apply
    and fires no duplicate side effects."""
    if not is_early_returnable(db, request, today):
        _notify(client, request["employee_id"], CANNOT_CANCEL)
        return
    reclaimed = early_return_reclaim_days(db, request, today)
    if not early_return(db, request["request_id"], today):
        _notify(client, request["employee_id"], CANNOT_CANCEL)
        return
    employee = get_employee(db, request["employee_id"])
    leave_type, start = request["leave_type"], request["start_date"]

    if request["calendar_event_id"]:
        # The calendar client can only patch a title, so re-date by delete + recreate.
        calendar.delete_event(request["calendar_event_id"])
        event_id = calendar.create_event(
            f"{employee['real_name']} — {leave_type}",
            start,
            today,
            color_id_for(employee["slack_user_id"]),
        )
        set_calendar_event_id(db, request["request_id"], event_id)

    update_board(
        db,
        client,
        today,
        sheets,
        add={
            "request_id": request["request_id"],
            "name": employee["real_name"],
            "type": leave_type,
            "start": start,
            "end": today,
            "half": None,
        },
    )

    if not _self_approves(employee):  # only FYI a real, distinct manager
        _notify(
            client,
            employee["manager_id"],
            f"FYI: {employee['real_name']} returned early from their {leave_type} leave — "
            f"now {format_period(start, today)} ({reclaimed} day(s) returned).",
        )
    _notify(
        client,
        employee["slack_user_id"],
        f"Your {leave_type} leave ended early — kept through {today.isoformat()}, "
        f"{reclaimed} day(s) returned to your balance.",
    )


def submit_cancel(ack, body, view, client, db, calendar, sheets=None, today=None):
    ack()
    today = today or date.today()
    request_id = view["state"]["values"]["request"]["value"]["selected_option"]["value"]
    request = get_request(db, request_id)

    if request is None:
        # The row vanished between opening the modal and submitting (e.g. /control
        # Clear, or the employee was removed) — nothing left to cancel.
        _notify(client, body["user"]["id"], CANNOT_CANCEL)
        return
    if body["user"]["id"] != request["employee_id"]:
        return
    if not can_cancel(request, today):
        _notify(client, body["user"]["id"], CANNOT_CANCEL)
        return

    if is_in_progress(request, today):
        _early_return(db, calendar, client, sheets, request, today)
        return

    status_before = request["status"]
    if not cancel_request(db, request_id):
        # A concurrent cancel/decision already moved this request; do nothing further.
        return
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
