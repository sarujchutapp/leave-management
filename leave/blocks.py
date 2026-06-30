"""Block Kit view builders."""

import json

LEAVE_TYPES = ["sick", "vacation", "personal"]

LEAVE_CALLBACK_ID = "leave_submit"
# /advance "Book" button: opens the apply modal pre-filled with a suggested
# break's dates. The button value is "start|end" (ISO), both vacation full-day.
ADVANCE_BOOK_ACTION = "advance_book"
# /advance "Plan a group break" button -> the people-picker modal (group-break finder).
GROUP_PICK_ACTION = "advance_group_pick"
GROUP_CALLBACK_ID = "advance_group_submit"
# /burnout board is rendered as a modal (scrolls within a bounded window, unlike a
# long DM). The board reads several records, so it opens a loading modal in the ack
# window and is filled in post-ack via views_update keyed by external_id.
BURNOUT_VIEW_CALLBACK_ID = "burnout_board"
# Refresh button: rebuilds the board in place (it's a live snapshot).
BURNOUT_REFRESH_ACTION = "burnout_refresh"
# "Nudge" button on a row: the bot DMs the at-risk report a supportive wellbeing
# message. The button value is a JSON blob of the row the manager saw (target,
# name, stretch, expiring) so the DM cites that reason without a re-read.
NUDGE_ACTION = "burnout_nudge"
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
# The manage-employees Action select dispatches a block action so the modal can
# show only the fields each action needs; it needs its own action_id to route that.
MANAGE_ACTION_SELECT = "manage_action_select"
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
HOLIDAYS_CALLBACK_ID = "control_holidays_submit"
HOLIDAYS_ACTION = "control_holidays"
HOLIDAYS_ACTION_SELECT = "holiday_action_select"
# Checkboxes that toggle whether a cap is enforced; toggling re-renders the modal.
CONSECUTIVE_TOGGLE_ACTION = "control_enforce_consecutive"
CARRY_OVER_TOGGLE_ACTION = "control_enable_carry_over"


def format_period(start, end, half=None):
    """Human-readable leave period. A half-day is a single date and shows which
    half, so messages distinguish it from a full day."""
    if half:
        return f"{start} ({half} half)"
    return f"{start} → {end}"


def _leave_type_options():
    return [
        {"text": {"type": "plain_text", "text": t.capitalize()}, "value": t} for t in LEAVE_TYPES
    ]


def build_leave_modal(balances=None, prefill=None):
    """The /dayoff request modal. If balances ({type: days_left}) is given, a
    context line at the top shows the remaining balance per leave type. `prefill`
    ({"leave_type","start","end"} with ISO date strings), when given, pre-fills the
    form — used by /advance's Book button to open this modal on a suggested break."""
    prefill = prefill or {}
    blocks = []

    if balances:
        summary = "   ·   ".join(f"*{t}*: {balances[t]}" for t in LEAVE_TYPES)
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"Days left — {summary}"}],
            }
        )

    leave_type_el = {
        "type": "static_select",
        "action_id": "value",
        "options": _leave_type_options(),
    }
    if prefill.get("leave_type"):
        leave_type_el["initial_option"] = {
            "text": {"type": "plain_text", "text": prefill["leave_type"].capitalize()},
            "value": prefill["leave_type"],
        }
    start_el = {"type": "datepicker", "action_id": "value"}
    if prefill.get("start"):
        start_el["initial_date"] = prefill["start"]
    end_el = {"type": "datepicker", "action_id": "value"}
    if prefill.get("end"):
        end_el["initial_date"] = prefill["end"]

    blocks.extend(
        [
            {
                "type": "input",
                "block_id": "leave_type",
                "label": {"type": "plain_text", "text": "Leave type"},
                "element": leave_type_el,
            },
            {
                "type": "input",
                "block_id": "start_date",
                "label": {"type": "plain_text", "text": "Start date"},
                "element": start_el,
            },
            {
                "type": "input",
                "block_id": "end_date",
                "optional": True,
                "label": {"type": "plain_text", "text": "End date"},
                "hint": {"type": "plain_text", "text": "Leave empty for a single-day leave."},
                "element": end_el,
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


_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def _short_range(start, end):
    """Compact booking range, e.g. "Jun 8", "Jun 8–12", or "Jun 29 – Jul 3"."""
    if start == end:
        return f"{_MONTHS[start.month - 1]} {start.day}"
    if start.month == end.month:
        return f"{_MONTHS[start.month - 1]} {start.day}–{end.day}"
    return f"{_MONTHS[start.month - 1]} {start.day} – {_MONTHS[end.month - 1]} {end.day}"


def _advance_option_line(index, brk):
    # Compact for the small modal: days-off length, quota used, and the booking dates
    # in short form (the same dates the Book button pre-fills in the apply modal).
    off = "day" if brk.span_days == 1 else "days"
    used = "day" if brk.cost == 1 else "days"
    dates = _short_range(brk.book_start, brk.book_end)
    return f"*{index}.* *{brk.span_days} {off} off* · {brk.cost} {used} used ({dates})"


def build_advance_blocks(breaks):
    """/advance reply blocks: a header plus one section per suggested break, each
    with a Book button that opens the apply modal pre-filled with that break's
    dates (value `start|end`, ISO). `breaks` is non-empty."""
    header = (
        "🌴 Your best break options this year:"
        if len(breaks) > 1
        else "🌴 Your longest possible break this year:"
    )
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": header}}]
    for i, brk in enumerate(breaks, 1):
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": _advance_option_line(i, brk)},
                "accessory": {
                    "type": "button",
                    "action_id": ADVANCE_BOOK_ACTION,
                    "text": {"type": "plain_text", "text": "Book"},
                    "value": f"{brk.book_start.isoformat()}|{brk.book_end.isoformat()}",
                },
            }
        )
    blocks.append(
        {
            "type": "actions",
            "block_id": "advance_group",
            "elements": [
                {
                    "type": "button",
                    "action_id": GROUP_PICK_ACTION,
                    "text": {"type": "plain_text", "text": "👥 Plan a group break"},
                    "value": "group",
                }
            ],
        }
    )
    return blocks


def build_advance_modal(breaks, empty_text):
    """The /advance modal: the same option content as `build_advance_blocks` (one
    section + Book button per break, then the group-break button) when `breaks` is
    non-empty, or a single note (`empty_text`) when there's nothing to suggest. A
    display-only modal — Close, no submit."""
    blocks = (
        build_advance_blocks(breaks)
        if breaks
        else [{"type": "section", "text": {"type": "mrkdwn", "text": empty_text}}]
    )
    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "Leave Optimizer"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": blocks,
    }


def _risk_dot(stretch):
    """A quick-scan risk band keyed purely to the no-break stretch (the primary
    burnout measure). The exact day counts stay on the row, so the dot is a visual
    aid, not an opaque score — and the legend spells the thresholds out. 🔴 90+
    days since last leave (~3 months), 🟠 45+, 🟢 under 45."""
    if stretch >= 90:
        return "🔴"
    if stretch >= 45:
        return "🟠"
    return "🟢"


# Cap rows so the view stays under Slack's 100-block ceiling. Each row is 3 blocks
# (a separator divider + the card + the Nudge actions row) plus a few fixed blocks,
# so 30 rows ≈ 94 blocks. Far above any real manager's direct-report count.
_BURNOUT_MAX_ROWS = 30


def _burnout_modal_view(blocks, external_id=None):
    """The /burnout board modal shell. `external_id`, when set, lets the post-ack
    views_update find the loading view opened in the ack window."""
    view = {
        "type": "modal",
        "callback_id": BURNOUT_VIEW_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "🔥 Burnout Board"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": blocks,
    }
    if external_id:
        view["external_id"] = external_id
    return view


def build_burnout_loading_modal(external_id):
    """The instant placeholder opened on the trigger_id while the board is built
    post-ack (the build reads several records, past Slack's 3s ack window)."""
    return _burnout_modal_view(
        [{"type": "section", "text": {"type": "mrkdwn", "text": "⏳ Building your burnout board…"}}],
        external_id,
    )


def _burnout_row_blocks(rank, s, avatar_url=None):
    """One ranked report as a single card: the name (rank, risk dot) over a tidy
    vertical list of the flags that matter — days since last leave, vacation left,
    and the next booked break (relief) — with the profile picture filling the right
    (when known), then a Nudge button beneath. The dot only bands the visible
    no-break stretch, never an opaque score."""
    next_break = f"{s.next_break:%b} {s.next_break.day}" if s.next_break else "Nothing booked"
    card = {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                f"{_risk_dot(s.stretch)}  *#{rank} · {s.name}*\n"
                f"*Days since last leave:*  {s.stretch}\n"
                f"*Vacation left:*  {s.remaining} days\n"
                f"*Next break:*  {next_break}"
            ),
        },
    }
    if avatar_url:
        card["accessory"] = {"type": "image", "image_url": avatar_url, "alt_text": s.name}
    return [
        card,
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": NUDGE_ACTION,
                    "text": {"type": "plain_text", "text": "🌿 Nudge"},
                    "value": json.dumps(
                        {"user_id": s.user_id, "name": s.name, "stretch": s.stretch, "expiring": s.expiring}
                    ),
                }
            ],
        },
    ]


def build_burnout_board_modal(signals, external_id=None, avatars=None):
    """The filled /burnout board: one ranked card per direct report (most at risk
    first), a risk legend, and a Refresh button. `avatars` maps user_id -> profile
    image URL (omitted rows just show no picture). `signals` may be empty (a manager
    whose reports all left since the board opened) — then it says so plainly."""
    if not signals:
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "You don't manage anyone right now."}}
        ]
        return _burnout_modal_view(blocks, external_id)
    avatars = avatars or {}
    blocks = [
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "Your direct reports, ranked by burnout risk — most at risk first."}
            ],
        },
    ]
    # A divider before each card separates one person from the next (Block Kit modals
    # have no per-card colour, so a line is the separator).
    for rank, s in enumerate(signals[:_BURNOUT_MAX_ROWS], 1):
        blocks.append({"type": "divider"})
        blocks += _burnout_row_blocks(rank, s, avatars.get(s.user_id))
    if len(signals) > _BURNOUT_MAX_ROWS:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"Showing the {_BURNOUT_MAX_ROWS} most at risk of {len(signals)}."}
                ],
            }
        )
    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "Risk: 🔴 90+ days since last leave · 🟠 45+ · 🟢 under 45"}
            ],
        }
    )
    blocks.append(
        {
            "type": "actions",
            "block_id": "burnout_refresh",
            "elements": [
                {
                    "type": "button",
                    "action_id": BURNOUT_REFRESH_ACTION,
                    "text": {"type": "plain_text", "text": "🔄 Refresh"},
                    "value": "refresh",
                }
            ],
        }
    )
    return _burnout_modal_view(blocks, external_id)


def mark_row_nudged(view, value):
    """The manager's in-place confirmation: replace the Nudge button matching `value`
    with a '✓ Nudged' marker, returning the updated modal view for views_update. (A
    nudge persists nothing, so this lives only in the view.)"""
    blocks = []
    for b in view["blocks"]:
        if b.get("type") == "actions" and any(
            e.get("action_id") == NUDGE_ACTION and e.get("value") == value
            for e in b.get("elements", [])
        ):
            b = {"type": "context", "elements": [{"type": "mrkdwn", "text": "✓ Nudged"}]}
        blocks.append(b)
    return _burnout_modal_view(blocks, view.get("external_id"))


def build_group_result_blocks(window, text):
    """The group-break result message: the shareable text plus a "Book mine"
    button that opens the apply modal pre-filled with the shared window's dates
    for the requester only (reuses ADVANCE_BOOK_ACTION). `window` is (start, end);
    `text` is the copy-pasteable line kept as the message body."""
    start, end = window
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {
            "type": "actions",
            "block_id": "group_book",
            "elements": [
                {
                    "type": "button",
                    "action_id": ADVANCE_BOOK_ACTION,
                    "text": {"type": "plain_text", "text": "Book mine"},
                    "value": f"{start.isoformat()}|{end.isoformat()}",
                }
            ],
        },
    ]


def build_group_picker_modal():
    """Modal to pick teammates for the group-break finder. The caller is always
    included, so the picker is optional — submitting with nobody selected just
    finds the caller's own window."""
    return {
        "type": "modal",
        "callback_id": GROUP_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Group break"},
        "submit": {"type": "plain_text", "text": "Find window"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Pick teammates to find a window you can *all* take off together. "
                    "You're included automatically.",
                },
            },
            {
                "type": "input",
                "block_id": "people",
                "optional": True,
                "label": {"type": "plain_text", "text": "People"},
                "element": {
                    "type": "multi_users_select",
                    "action_id": "value",
                    "placeholder": {"type": "plain_text", "text": "Pick teammates"},
                },
            },
        ],
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
    (HOLIDAYS_ACTION, "Holidays"),
    (CLEAR_ACTION, "Clear"),
    (REPORT_ACTION, "Report"),
    (MANAGE_EMPLOYEES_ACTION, "Manage employees"),
    (VIEW_SETTINGS_ACTION, "View settings"),
]


_HOLIDAY_ACTIONS = [
    {"text": {"type": "plain_text", "text": "Add a holiday"}, "value": "add"},
    {"text": {"type": "plain_text", "text": "Remove a holiday"}, "value": "remove"},
]


def build_holidays_modal(holidays, action="add"):
    """Admin holidays modal. An Action select chooses Add or Remove and dispatches a
    block action that re-renders this modal, so exactly one action is in play and its
    fields are required (no ambiguous all-optional submit). Add shows a date + label;
    Remove shows a dropdown of the current holidays (or a note when there are none).
    `holidays` is a list of (date, label, event_id)."""
    initial = next((o for o in _HOLIDAY_ACTIONS if o["value"] == action), _HOLIDAY_ACTIONS[0])
    blocks = [
        {
            "type": "input",
            "block_id": "holiday_action",
            "dispatch_action": True,  # re-render the modal when the action changes
            "label": {"type": "plain_text", "text": "Action"},
            "element": {
                "type": "static_select",
                "action_id": HOLIDAYS_ACTION_SELECT,
                "initial_option": initial,
                "options": _HOLIDAY_ACTIONS,
            },
        },
    ]
    if action == "remove":
        if holidays:
            blocks.append(
                {
                    "type": "input",
                    "block_id": "holiday_remove",
                    "label": {"type": "plain_text", "text": "Holiday to remove"},
                    "element": {
                        "type": "static_select",
                        "action_id": "value",
                        "placeholder": {"type": "plain_text", "text": "Pick one to remove"},
                        "options": [
                            {
                                "text": {"type": "plain_text", "text": f"{d.isoformat()} — {label}"[:75]},
                                "value": d.isoformat(),
                            }
                            for d, label, _ in holidays
                        ],
                    },
                }
            )
        else:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": "No holidays to remove yet."}],
                }
            )
    else:  # add
        blocks += [
            {
                "type": "input",
                "block_id": "holiday_date",
                "label": {"type": "plain_text", "text": "Date"},
                "element": {"type": "datepicker", "action_id": "value"},
            },
            {
                "type": "input",
                "block_id": "holiday_label",
                "label": {"type": "plain_text", "text": "Label"},
                "element": {"type": "plain_text_input", "action_id": "value"},
            },
        ]
    return {
        "type": "modal",
        "callback_id": HOLIDAYS_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Holidays"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Back"},
        "blocks": blocks,
    }


# Slack shows the first 5 buttons in an actions block and collapses the rest into a
# "…" overflow, so the buttons are spread across actions blocks of at most this many.
_MENU_ROW = 4


def build_control_menu():
    """The /control admin menu: a button per admin action. No submit — each button is a
    block action that opens its own sub-modal. Buttons are chunked across actions blocks
    so none are hidden behind Slack's overflow (see _MENU_ROW)."""
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "Pick an admin action:"}},
    ]
    for i in range(0, len(_CONTROL_BUTTONS), _MENU_ROW):
        blocks.append(
            {
                "type": "actions",
                "block_id": f"control_actions_{i // _MENU_ROW}",
                "elements": [
                    {
                        "type": "button",
                        "action_id": action_id,
                        "text": {"type": "plain_text", "text": label},
                    }
                    for action_id, label in _CONTROL_BUTTONS[i : i + _MENU_ROW]
                ],
            }
        )
    return {
        "type": "modal",
        "callback_id": CONTROL_MENU_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Admin Control"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": blocks,
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


def _toggle_checkbox(block_id, action_id, label, checked):
    """A single-option checkbox that re-renders the modal when toggled."""
    option = {"text": {"type": "plain_text", "text": label}, "value": "on"}
    element = {"type": "checkboxes", "action_id": action_id, "options": [option]}
    if checked:
        element["initial_options"] = [option]
    return {
        "type": "input",
        "block_id": block_id,
        "optional": True,
        "dispatch_action": True,
        "label": {"type": "plain_text", "text": label},
        "element": element,
    }


def build_leave_limits_modal(policy):
    """Edit base allowance per type + the vacation consecutive limit, pre-filled from
    the current central policy. The consecutive limit can be turned off (checkbox); when
    off, its number field is hidden (rendered from the stored state at open, re-rendered
    on toggle)."""
    allowances = policy["allowances"]
    consecutive = policy["consecutive_limit"]["vacation"]
    enforce = consecutive is not None
    blocks = [
        _number_input("sick", "Sick allowance (days)", allowances["sick"]),
        _number_input("vacation", "Vacation allowance (days)", allowances["vacation"]),
        _number_input("personal", "Personal allowance (days)", allowances["personal"]),
        _toggle_checkbox(
            "enforce_consecutive",
            CONSECUTIVE_TOGGLE_ACTION,
            "Enforce a consecutive limit on vacation",
            enforce,
        ),
    ]
    if enforce:
        blocks.append(
            _number_input("consecutive_limit", "Vacation consecutive limit (days)", consecutive)
        )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Lowering the vacation allowance takes effect immediately and can push "
                    "balances negative for anyone who has already used more than the new amount "
                    "(this blocks their new bookings until the year resets).",
                }
            ],
        }
    )
    return {
        "type": "modal",
        "callback_id": LEAVE_LIMITS_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Leave Limits"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Back"},
        "blocks": blocks,
    }


def build_carry_over_modal(policy):
    """Edit the vacation carry-over caps, pre-filled from the current central policy.
    Carry-over can be turned off (checkbox); when off (max carry over 0) its field is
    hidden. Max total is always shown. Rendered from the stored state at open,
    re-rendered on toggle."""
    max_carry_over = policy["max_carry_over"]["vacation"]
    enabled = max_carry_over > 0
    blocks = [
        _toggle_checkbox(
            "enable_carry_over", CARRY_OVER_TOGGLE_ACTION, "Enable carry-over", enabled
        ),
    ]
    if enabled:
        blocks.append(
            _number_input("max_carry_over", "Max carry over (vacation days)", max_carry_over)
        )
    blocks.append(
        _number_input("max_total", "Max total (vacation days)", policy["max_total"]["vacation"])
    )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Lowering a cap recomputes everyone's carry-in immediately — "
                    "balances can drop, and go negative until the year resets (which blocks "
                    "new bookings). Raising it back restores them.",
                }
            ],
        }
    )
    return {
        "type": "modal",
        "callback_id": CARRY_OVER_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Carry-over"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Back"},
        "blocks": blocks,
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


def _optional_text(block_id, label, initial=None):
    element = {"type": "plain_text_input", "action_id": "value"}
    if initial is not None:
        element["initial_value"] = str(initial)
    return {
        "type": "input",
        "block_id": block_id,
        "optional": True,
        "label": {"type": "plain_text", "text": label},
        "element": element,
    }


_MANAGE_ACTIONS = [
    {"text": {"type": "plain_text", "text": "Add / edit"}, "value": "save"},
    {"text": {"type": "plain_text", "text": "Set allowance override"}, "value": "override"},
    {"text": {"type": "plain_text", "text": "Delete"}, "value": "delete"},
]


def build_manage_employees_modal(action="save", selected_user=None, employee=None):
    """Add/edit, set an allowance override, or delete an employee. The Action select
    and the Employee picker both dispatch a block action so the modal re-renders —
    the Action select shows only the fields that action needs, and picking an Employee
    prefills their current name/manager/override (blank for someone not yet in the
    system). Employee + Manager are Slack user-pickers, so member IDs are supplied
    directly. Delete is block-and-tell: a person who still manages anyone is rejected
    until reassigned. `employee` is the picked person's stored record (or None)."""
    initial = next((o for o in _MANAGE_ACTIONS if o["value"] == action), _MANAGE_ACTIONS[0])
    overrides = (employee or {}).get("allowances") or {}
    employee_element = {
        "type": "users_select",
        "action_id": "value",
        "placeholder": {"type": "plain_text", "text": "Pick a person"},
    }
    if selected_user:
        employee_element["initial_user"] = selected_user
    blocks = [
        {
            "type": "input",
            "block_id": "employee",
            "dispatch_action": True,  # re-render with the picked person's values prefilled
            "label": {"type": "plain_text", "text": "Employee"},
            "element": employee_element,
        },
        {
            "type": "input",
            "block_id": "action",
            "dispatch_action": True,  # re-render the modal when the action changes
            "label": {"type": "plain_text", "text": "Action"},
            "element": {
                "type": "static_select",
                "action_id": MANAGE_ACTION_SELECT,
                "initial_option": initial,
                "options": _MANAGE_ACTIONS,
            },
        },
    ]

    if action == "save":
        name_element = {"type": "plain_text_input", "action_id": "value"}
        if employee and employee.get("real_name"):
            name_element["initial_value"] = employee["real_name"]
        manager_element = {
            "type": "users_select",
            "action_id": "value",
            "placeholder": {"type": "plain_text", "text": "Pick the approver"},
        }
        if employee and employee.get("manager_id"):
            manager_element["initial_user"] = employee["manager_id"]
        blocks += [
            {
                "type": "input",
                "block_id": "name",
                "label": {"type": "plain_text", "text": "Name"},
                "element": name_element,
            },
            {
                "type": "input",
                "block_id": "manager",
                "label": {"type": "plain_text", "text": "Manager"},
                "hint": {
                    "type": "plain_text",
                    "text": "The approver. Pick the person themselves if they're top of chain "
                    "(their leave auto-approves).",
                },
                "element": manager_element,
            },
        ]
    elif action == "override":
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Per-person allowance override. Leave all three blank to clear "
                        "the override (fall back to the central policy).",
                    }
                ],
            }
        )
        blocks += [
            _optional_text("override_sick", "Sick override", overrides.get("sick")),
            _optional_text("override_vacation", "Vacation override", overrides.get("vacation")),
            _optional_text("override_personal", "Personal override", overrides.get("personal")),
        ]
    else:  # delete
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Permanently removes this employee. Blocked while they still "
                        "manage anyone — reassign those reports first.",
                    }
                ],
            }
        )

    return {
        "type": "modal",
        "callback_id": MANAGE_EMPLOYEES_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Manage Employees"},
        "submit": {"type": "plain_text", "text": "Apply"},
        "close": {"type": "plain_text", "text": "Back"},
        "blocks": blocks,
    }


def build_report_modal(report_type="quota", employees=None):
    """Pick which report to send: all-employee quota, one person's full leave
    history, or team burnout risk. The person picker is only shown once "history"
    is chosen — the report-type select dispatches a block action that re-renders
    this modal. The person picker is a dropdown of *registered employees* (so it
    can't list bots/apps the way a Slack user-picker would). The CSV is DMed to
    the requesting admin."""
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
        people = sorted(employees or [], key=lambda e: e.get("real_name", ""))
        if people:
            blocks.append(
                {
                    "type": "input",
                    "block_id": "person",
                    "label": {"type": "plain_text", "text": "Person"},
                    "element": {
                        "type": "static_select",
                        "action_id": "value",
                        "placeholder": {"type": "plain_text", "text": "Pick an employee"},
                        "options": [
                            {
                                "text": {
                                    "type": "plain_text",
                                    "text": (p.get("real_name") or p["slack_user_id"])[:75],
                                },
                                "value": p["slack_user_id"],
                            }
                            for p in people
                        ],
                    },
                }
            )
        else:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": "No registered employees yet."}
                    ],
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
    max_carry_over = policy["max_carry_over"]["vacation"]
    carry_over = "disabled" if max_carry_over == 0 else max_carry_over
    consecutive = policy["consecutive_limit"]["vacation"]
    consecutive_text = "No limit" if consecutive is None else consecutive
    lines = [
        f"*Allowances* — {allowances}",
        f"*Max carry over* (vacation): {carry_over}",
        f"*Max total* (vacation): {policy['max_total']['vacation']}",
        f"*Consecutive limit* (vacation): {consecutive_text}",
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
