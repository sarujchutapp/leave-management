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


def build_ticket(request_id, employee_name, leave_type, start, end, reason, remaining, half=None):
    """Manager's approval ticket: details + Approve/Decline buttons."""
    detail = f"*{employee_name}* requests *{leave_type}* leave\n{format_period(start, end, half)}"
    context = f"Balance left for {leave_type}: {remaining}"
    if reason:
        context += f"\nReason: {reason}"
    rid = str(request_id)
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": detail}},
        {"type": "section", "text": {"type": "mrkdwn", "text": context}},
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
        },
    ]


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
