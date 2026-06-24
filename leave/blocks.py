"""Block Kit view builders."""

LEAVE_TYPES = ["sick", "vacation", "personal"]

LEAVE_CALLBACK_ID = "leave_submit"
# /advance "Book" button: opens the apply modal pre-filled with a suggested
# break's dates. The button value is "start|end" (ISO), both vacation full-day.
ADVANCE_BOOK_ACTION = "advance_book"
# /advance "Plan a group break" button -> the people-picker modal (group-break finder).
GROUP_PICK_ACTION = "advance_group_pick"
GROUP_CALLBACK_ID = "advance_group_submit"
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


def _advance_option_line(index, brk):
    book = brk.book_start.isoformat()
    if brk.book_end != brk.book_start:
        book += f" → {brk.book_end.isoformat()}"
    unit = "day" if brk.cost == 1 else "days"
    return (
        f"*{index}.* Book vacation *{book}* ({brk.cost} {unit}) → "
        f"*{brk.span_days} days off* ({brk.span_start.isoformat()} → {brk.span_end.isoformat()})"
    )


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


def build_burnout_board_blocks(signals):
    """/burnout board reply blocks: a header plus one section per direct report,
    ranked by no-break stretch (longest first). Each row spells out the explainable
    flags — days since last leave, remaining vacation vs days left in the year, and
    longest working stretch — never an opaque score. `signals` is non-empty."""
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "🔥 *Burnout board* — your direct reports, most at risk first:",
            },
        }
    ]
    for s in signals:
        expiring = (
            f"⚠️ {s.expiring} vacation days expiring Dec 31"
            if s.expiring
            else "no vacation expiring this year"
        )
        line = (
            f"*{s.name}*\n"
            f"• {s.stretch} days since last leave\n"
            f"• {s.remaining} vacation days left · {s.days_left} days left in the year\n"
            f"• longest working stretch: {s.working} days\n"
            f"• {expiring}"
        )
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": line}})
    return blocks


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


def build_holidays_modal(holidays):
    """Admin holidays modal: add a holiday (date + label), or remove an existing
    one. All inputs are optional; the submit applies a remove if one is picked,
    otherwise an add. `holidays` is a list of (date, label, event_id) for the
    remove dropdown (omitted when there are none yet)."""
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Add* a holiday (date + label), or *remove* one below.",
            },
        },
        {
            "type": "input",
            "block_id": "holiday_date",
            "optional": True,
            "label": {"type": "plain_text", "text": "Date"},
            "element": {"type": "datepicker", "action_id": "value"},
        },
        {
            "type": "input",
            "block_id": "holiday_label",
            "optional": True,
            "label": {"type": "plain_text", "text": "Label"},
            "element": {"type": "plain_text_input", "action_id": "value"},
        },
    ]
    if holidays:
        blocks.append(
            {
                "type": "input",
                "block_id": "holiday_remove",
                "optional": True,
                "label": {"type": "plain_text", "text": "Remove a holiday"},
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
    return {
        "type": "modal",
        "callback_id": HOLIDAYS_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Holidays"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Back"},
        "blocks": blocks,
    }


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


_MANAGE_ACTIONS = [
    {"text": {"type": "plain_text", "text": "Add / edit"}, "value": "save"},
    {"text": {"type": "plain_text", "text": "Set allowance override"}, "value": "override"},
    {"text": {"type": "plain_text", "text": "Delete"}, "value": "delete"},
]


def build_manage_employees_modal(action="save"):
    """Add/edit, set an allowance override, or delete an employee. The Action select
    dispatches a block action so the modal shows only the fields the chosen action
    needs (re-rendered via views_update). Employee + Manager are Slack user-pickers,
    so member IDs are supplied directly. Delete is block-and-tell: a person who still
    manages anyone is rejected until reassigned."""
    initial = next((o for o in _MANAGE_ACTIONS if o["value"] == action), _MANAGE_ACTIONS[0])
    blocks = [
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
        blocks += [
            {
                "type": "input",
                "block_id": "name",
                "label": {"type": "plain_text", "text": "Name"},
                "element": {"type": "plain_text_input", "action_id": "value"},
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
                "element": {
                    "type": "users_select",
                    "action_id": "value",
                    "placeholder": {"type": "plain_text", "text": "Pick the approver"},
                },
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
            _optional_text("override_sick", "Sick override"),
            _optional_text("override_vacation", "Vacation override"),
            _optional_text("override_personal", "Personal override"),
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
