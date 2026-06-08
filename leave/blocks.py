"""Block Kit view builders."""

LEAVE_TYPES = ["sick", "vacation", "personal"]

LEAVE_CALLBACK_ID = "leave_submit"


def build_leave_modal(balances=None):
    """The /leave request modal. If balances ({type: days_left}) is given, a
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
