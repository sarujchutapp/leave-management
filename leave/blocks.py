"""Block Kit view builders."""

LEAVE_TYPES = ["sick", "vacation", "personal"]

LEAVE_CALLBACK_ID = "leave_submit"
APPROVE_ACTION = "approve_request"
DECLINE_ACTION = "decline_request"
DECLINE_CALLBACK_ID = "decline_submit"
CANCEL_CALLBACK_ID = "cancel_submit"

# Admin control plane (/control). The menu is a modal of buttons; each button is a
# block action routing to a sub-modal. Only View Settings is wired in this slice.
CONTROL_MENU_CALLBACK_ID = "control_menu"
SETTINGS_VIEW_CALLBACK_ID = "control_settings_view"
LEAVE_LIMITS_CALLBACK_ID = "control_leave_limits_submit"
CARRY_OVER_CALLBACK_ID = "control_carry_over_submit"
CLEAR_CALLBACK_ID = "control_clear_submit"
# Typed exactly to confirm the destructive Clear wipe.
CLEAR_CONFIRM_WORD = "CLEAR"
MANAGE_EMPLOYEES_CALLBACK_ID = "control_manage_employees_submit"
REPORT_CALLBACK_ID = "control_report_submit"
# The report-type select dispatches a block action (so the modal can reveal the
# person picker for "history"); it needs its own action_id to route that event.
REPORT_TYPE_ACTION = "report_type_select"
VIEW_SETTINGS_ACTION = "control_view_settings"
LEAVE_LIMITS_ACTION = "control_leave_limits"
CARRY_OVER_ACTION = "control_carry_over"
CLEAR_ACTION = "control_clear"
REPORT_ACTION = "control_report"
MANAGE_EMPLOYEES_ACTION = "control_manage_employees"


def format_period(start, end, half=None):
    """Human-readable leave period. A half-day is a single date and shows which
    half, so messages distinguish it from a full day."""
    if half:
        return f"{start} ({half} half)"
    return f"{start} → {end}"


def build_leave_modal(balances=None):
    """The /dayoff request modal. If balances ({type: days_left}) is given, a
    context line at the top shows the remaining balance per leave type."""
    blocks = []

    if balances:
        summary = "   ·   ".join(f"*{t}*: {balances[t]}" for t in LEAVE_TYPES)
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"Days left — {summary}"}],
            }
        )

    blocks.extend(
        [
            {
                "type": "input",
                "block_id": "leave_type",
                "label": {"type": "plain_text", "text": "Leave type"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "options": [
                        {"text": {"type": "plain_text", "text": t.capitalize()}, "value": t}
                        for t in LEAVE_TYPES
                    ],
                },
            },
            {
                "type": "input",
                "block_id": "start_date",
                "label": {"type": "plain_text", "text": "Start date"},
                "element": {"type": "datepicker", "action_id": "value"},
            },
            {
                "type": "input",
                "block_id": "end_date",
                "optional": True,
                "label": {"type": "plain_text", "text": "End date"},
                "hint": {"type": "plain_text", "text": "Leave empty for a single-day leave."},
                "element": {"type": "datepicker", "action_id": "value"},
            },
            {
                "type": "input",
                "block_id": "half_day",
                "label": {"type": "plain_text", "text": "Half day?"},
                "hint": {
                    "type": "plain_text",
                    "text": "Morning/afternoon applies to a single-day leave only.",
                },
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "initial_option": {
                        "text": {"type": "plain_text", "text": "Full day"},
                        "value": "full",
                    },
                    "options": [
                        {"text": {"type": "plain_text", "text": "Full day"}, "value": "full"},
                        {"text": {"type": "plain_text", "text": "Morning"}, "value": "morning"},
                        {
                            "text": {"type": "plain_text", "text": "Afternoon"},
                            "value": "afternoon",
                        },
                    ],
                },
            },
            {
                "type": "input",
                "block_id": "reason",
                "optional": True,
                "label": {"type": "plain_text", "text": "Reason"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "value",
                    "multiline": True,
                },
            },
        ]
    )

    return {
        "type": "modal",
        "callback_id": LEAVE_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Request Leave"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def build_ticket(
    request_id, employee_name, leave_type, start, end, reason, remaining, half=None, coverage_warning=None
):
    """Manager's approval ticket: details + Approve/Decline buttons. An optional
    Coverage Radar warning (peers already off over these dates) is shown as a
    heads-up section above the buttons; it never changes the decision."""
    detail = f"*{employee_name}* requests *{leave_type}* leave\n{format_period(start, end, half)}"
    context = f"Balance left for {leave_type}: {remaining}"
    if reason:
        context += f"\nReason: {reason}"
    rid = str(request_id)
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": detail}},
        {"type": "section", "text": {"type": "mrkdwn", "text": context}},
    ]
    if coverage_warning:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": coverage_warning}})
    blocks.append(
        {
            "type": "actions",
            "block_id": "ticket_actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": APPROVE_ACTION,
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "value": rid,
                },
                {
                    "type": "button",
                    "action_id": DECLINE_ACTION,
                    "style": "danger",
                    "text": {"type": "plain_text", "text": "Decline"},
                    "value": rid,
                },
            ],
        }
    )
    return blocks


def build_decline_modal(private_metadata):
    """Modal asking the manager for an optional decline reason."""
    return {
        "type": "modal",
        "callback_id": DECLINE_CALLBACK_ID,
        "private_metadata": private_metadata,
        "title": {"type": "plain_text", "text": "Decline Leave"},
        "submit": {"type": "plain_text", "text": "Decline"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "decline_reason",
                "optional": True,
                "label": {"type": "plain_text", "text": "Reason"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "value",
                    "multiline": True,
                },
            }
        ],
    }


def build_decision_notice(employee_name, leave_type, start, end, decision, reason=None, half=None):
    """Replaces the ticket's buttons once a decision is made."""
    text = f"{decision}: *{employee_name}* — {leave_type} {format_period(start, end, half)}"
    if reason:
        text += f"\nReason: {reason}"
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def build_cancel_modal(rows):
    """Modal listing the cancellable requests in a dropdown. Uses static_select
    (max 100 options) rather than radio_buttons (capped at 10) so a long backlog
    of upcoming/pending requests doesn't blow the limit and fail to open."""
    options = [
        {
            "text": {
                "type": "plain_text",
                "text": f"{r['leave_type']} · {format_period(r['start_date'], r['end_date'], r.get('half'))} ({r['status']})"[:75],
            },
            "value": str(r["request_id"]),
        }
        for r in rows
    ]
    return {
        "type": "modal",
        "callback_id": CANCEL_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Cancel Leave"},
        "submit": {"type": "plain_text", "text": "Cancel leave"},
        "close": {"type": "plain_text", "text": "Back"},
        "blocks": [
            {
                "type": "input",
                "block_id": "request",
                "label": {"type": "plain_text", "text": "Which request?"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "placeholder": {"type": "plain_text", "text": "Pick a request"},
                    "options": options,
                },
            }
        ],
    }


# Menu buttons, in display order. Each names an admin action; only View Settings
# is wired so far — the rest are present-but-inert until their slices land.
_CONTROL_BUTTONS = [
    (LEAVE_LIMITS_ACTION, "Leave limits"),
    (CARRY_OVER_ACTION, "Carry-over"),
    (CLEAR_ACTION, "Clear"),
    (REPORT_ACTION, "Report"),
    (MANAGE_EMPLOYEES_ACTION, "Manage employees"),
    (VIEW_SETTINGS_ACTION, "View settings"),
]


def build_control_menu():
    """The /control admin menu: a button per admin action. No submit — each button
    is a block action that opens its own sub-modal."""
    return {
        "type": "modal",
        "callback_id": CONTROL_MENU_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Admin Control"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "Pick an admin action:"},
            },
            {
                "type": "actions",
                "block_id": "control_actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": action_id,
                        "text": {"type": "plain_text", "text": label},
                    }
                    for action_id, label in _CONTROL_BUTTONS
                ],
            },
        ],
    }


def _number_input(block_id, label, value):
    """A single-line text input pre-filled with the current value. Numeric
    validation happens server-side on submit (see handlers), so the value is
    plain text here."""
    return {
        "type": "input",
        "block_id": block_id,
        "label": {"type": "plain_text", "text": label},
        "element": {
            "type": "plain_text_input",
            "action_id": "value",
            "initial_value": str(value),
        },
    }


def build_leave_limits_modal(policy):
    """Edit base allowance per type + the vacation consecutive limit, pre-filled
    from the current central policy."""
    allowances = policy["allowances"]
    return {
        "type": "modal",
        "callback_id": LEAVE_LIMITS_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Leave Limits"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Back"},
        "blocks": [
            _number_input("sick", "Sick allowance (days)", allowances["sick"]),
            _number_input("vacation", "Vacation allowance (days)", allowances["vacation"]),
            _number_input("personal", "Personal allowance (days)", allowances["personal"]),
            _number_input(
                "consecutive_limit",
                "Vacation consecutive limit (days)",
                policy["consecutive_limit"]["vacation"],
            ),
        ],
    }


def build_carry_over_modal(policy):
    """Edit the vacation carry-over caps, pre-filled from the current central policy."""
    return {
        "type": "modal",
        "callback_id": CARRY_OVER_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Carry-over"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Back"},
        "blocks": [
            _number_input(
                "max_carry_over",
                "Max carry over (vacation days)",
                policy["max_carry_over"]["vacation"],
            ),
            _number_input(
                "max_total",
                "Max total (vacation days)",
                policy["max_total"]["vacation"],
            ),
        ],
    }


def _optional_user_select(block_id, label, placeholder):
    return {
        "type": "input",
        "block_id": block_id,
        "optional": True,
        "label": {"type": "plain_text", "text": label},
        "element": {
            "type": "users_select",
            "action_id": "value",
            "placeholder": {"type": "plain_text", "text": placeholder},
        },
    }


def _optional_text(block_id, label):
    return {
        "type": "input",
        "block_id": block_id,
        "optional": True,
        "label": {"type": "plain_text", "text": label},
        "element": {"type": "plain_text_input", "action_id": "value"},
    }


def build_manage_employees_modal():
    """Add/edit (reuses the fields below) or delete an employee. The employee and
    manager are picked by Slack user-picker, so member IDs are supplied directly.
    Delete is block-and-tell: a manager with reports is rejected until reassigned."""
    return {
        "type": "modal",
        "callback_id": MANAGE_EMPLOYEES_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Manage Employees"},
        "submit": {"type": "plain_text", "text": "Apply"},
        "close": {"type": "plain_text", "text": "Back"},
        "blocks": [
            {
                "type": "input",
                "block_id": "employee",
                "label": {"type": "plain_text", "text": "Employee"},
                "element": {
                    "type": "users_select",
                    "action_id": "value",
                    "placeholder": {"type": "plain_text", "text": "Pick a person"},
                },
            },
            {
                "type": "input",
                "block_id": "action",
                "label": {"type": "plain_text", "text": "Action"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "initial_option": {
                        "text": {"type": "plain_text", "text": "Add / edit"},
                        "value": "save",
                    },
                    "options": [
                        {"text": {"type": "plain_text", "text": "Add / edit"}, "value": "save"},
                        {"text": {"type": "plain_text", "text": "Delete"}, "value": "delete"},
                    ],
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Add / edit uses the fields below. Delete ignores them and is "
                        "blocked while the person still manages anyone.",
                    }
                ],
            },
            _optional_text("name", "Name (add / edit)"),
            _optional_user_select("manager", "Manager (add / edit)", "Pick a manager"),
            _optional_text("override_sick", "Sick override (optional)"),
            _optional_text("override_vacation", "Vacation override (optional)"),
            _optional_text("override_personal", "Personal override (optional)"),
        ],
    }


def build_report_modal(report_type="quota"):
    """Pick which report to send: all-employee quota, or one person's full leave
    history. The person picker is only shown once "history" is chosen — the
    report-type select dispatches a block action that re-renders this modal with
    `report_type` flipped. The CSV is DMed to the requesting admin."""
    options = [
        {"text": {"type": "plain_text", "text": "All-employee quota"}, "value": "quota"},
        {"text": {"type": "plain_text", "text": "One person's leave history"}, "value": "history"},
        {"text": {"type": "plain_text", "text": "Team burnout risk"}, "value": "burnout"},
    ]
    initial = next((o for o in options if o["value"] == report_type), options[0])
    blocks = [
        {
            "type": "input",
            "block_id": "report_type",
            "dispatch_action": True,  # fire a block action on selection, to toggle the picker
            "label": {"type": "plain_text", "text": "Report"},
            "element": {
                "type": "static_select",
                "action_id": REPORT_TYPE_ACTION,
                "initial_option": initial,
                "options": options,
            },
        },
    ]
    if report_type == "history":
        blocks.append(
            {
                "type": "input",
                "block_id": "person",
                "label": {"type": "plain_text", "text": "Person"},
                "element": {
                    "type": "users_select",
                    "action_id": "value",
                    "placeholder": {"type": "plain_text", "text": "Pick a person"},
                },
            }
        )
    return {
        "type": "modal",
        "callback_id": REPORT_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Report"},
        "submit": {"type": "plain_text", "text": "Send"},
        "close": {"type": "plain_text", "text": "Back"},
        "blocks": blocks,
    }


def build_clear_modal():
    """Destructive wipe, gated by a typed confirmation word. Submitting anything
    but the exact word returns a validation error and wipes nothing."""
    return {
        "type": "modal",
        "callback_id": CLEAR_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Clear All Leave"},
        "submit": {"type": "plain_text", "text": "Clear"},
        "close": {"type": "plain_text", "text": "Back"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "This deletes *all* leave requests, their calendar events, and "
                        "resets the board. Employees, policy, and holidays are kept. "
                        "This cannot be undone."
                    ),
                },
            },
            {
                "type": "input",
                "block_id": "confirm",
                "label": {"type": "plain_text", "text": f"Type {CLEAR_CONFIRM_WORD} to confirm"},
                "element": {"type": "plain_text_input", "action_id": "value"},
            },
        ],
    }


def build_settings_view(policy):
    """Read-only view of the current central policy (allowances + caps)."""
    allowances = "   ·   ".join(
        f"*{t}*: {policy['allowances'][t]}" for t in LEAVE_TYPES
    )
    lines = [
        f"*Allowances* — {allowances}",
        f"*Max carry over* (vacation): {policy['max_carry_over']['vacation']}",
        f"*Max total* (vacation): {policy['max_total']['vacation']}",
        f"*Consecutive limit* (vacation): {policy['consecutive_limit']['vacation']}",
    ]
    return {
        "type": "modal",
        "callback_id": SETTINGS_VIEW_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Current Settings"},
        "close": {"type": "plain_text", "text": "Back"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}
        ],
    }
