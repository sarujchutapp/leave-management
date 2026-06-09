"""Block Kit view builders."""

LEAVE_TYPES = ["sick", "vacation", "personal"]

LEAVE_CALLBACK_ID = "leave_submit"
APPROVE_ACTION = "approve_request"
DECLINE_ACTION = "decline_request"
DECLINE_CALLBACK_ID = "decline_submit"
CANCEL_CALLBACK_ID = "cancel_submit"


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
                "label": {"type": "plain_text", "text": "End date"},
                "element": {"type": "datepicker", "action_id": "value"},
            },
            {
                "type": "input",
                "block_id": "reason",
                "optional": True,
                "label": {"type": "plain_text", "text": "Reason (optional)"},
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


def build_ticket(request_id, employee_name, leave_type, start, end, reason, remaining):
    """Manager's approval ticket: details + Approve/Decline buttons."""
    detail = f"*{employee_name}* requests *{leave_type}* leave\n{start} → {end}"
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
                "label": {"type": "plain_text", "text": "Reason (optional)"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "value",
                    "multiline": True,
                },
            }
        ],
    }


def build_decision_notice(employee_name, leave_type, start, end, decision, reason=None):
    """Replaces the ticket's buttons once a decision is made."""
    text = f"{decision}: *{employee_name}* — {leave_type} {start} → {end}"
    if reason:
        text += f"\nReason: {reason}"
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def build_cancel_modal(rows):
    """Modal showing the cancellable requests as radio options laid out directly
    on the modal (no dropdown to expand)."""
    options = [
        {
            "text": {
                "type": "plain_text",
                "text": f"{r['leave_type']} · {r['start_date']} → {r['end_date']} ({r['status']})"[:75],
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
                "element": {"type": "radio_buttons", "action_id": "value", "options": options},
            }
        ],
    }
