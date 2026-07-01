"""/burnout board — a manager's direct reports ranked by burnout risk, rendered
as a modal (it scrolls within a bounded window instead of flooding a DM).

The signal/ranking logic is exercised through the moto `db` fixture (prior art:
the burnout CSV tests); the command, manager gate, and the loading→filled modal
handshake are exercised at the handler seam with the Slack fakes.
"""

import json
from datetime import date

from leave.balance import count_weekdays
from leave.blocks import NUDGE_ACTION
from leave.db import get_employee
from leave.handlers import NOT_A_MANAGER, handle_nudge, open_burnout, refresh_burnout
from leave.holidays import upsert_holiday
from leave.policy import set_policy
from leave.report import build_burnout_csv, ranked_burnout_signals
from leave.requests import approve_request, create_request
from leave.seed import upsert_employee
from tests.fakes import FakeAck, FakeSlackClient

TODAY = date(2026, 6, 8)


def _approved_past_leave(db, emp_id, start, end):
    """An approved leave that has already ended (a 'taken' break)."""
    rid = create_request(db, emp_id, "vacation", start, end, None)
    approve_request(db, rid)
    return rid


def _command(user_id, trigger_id="T"):
    """A slash-command body (e.g. /burnout): user_id + the trigger_id the loading
    modal opens on."""
    return {"user_id": user_id, "trigger_id": trigger_id}


def _board_view(client):
    """The board view the loading modal was swapped for (the last views_update)."""
    return client.views_update_calls[-1]["view"]


def _view_text(view):
    """All rendered text of a modal view — section text, field grids, and context
    elements — flattened for substring checks."""
    parts = []
    for b in view["blocks"]:
        if isinstance(b.get("text"), dict):
            parts.append(b["text"]["text"])
        for f in b.get("fields", []):
            parts.append(f["text"])
        for e in b.get("elements", []):
            if not isinstance(e, dict):
                continue
            t = e.get("text")
            if isinstance(t, str):  # context element
                parts.append(t)
            elif isinstance(t, dict) and "text" in t:  # button element
                parts.append(t["text"])
    return "\n".join(parts)


def _board_text(client):
    return _view_text(_board_view(client))


def _nudge_buttons(view):
    """The Nudge button on each report row of a board view (in its actions block)."""
    return [
        e
        for b in view["blocks"]
        for e in b.get("elements", [])
        if isinstance(e, dict) and e.get("action_id") == NUDGE_ACTION
    ]


def test_ranked_signals_order_by_no_break_stretch_longest_first(db):
    set_policy(db)
    upsert_employee(db, "U_A", "Alice", None)
    upsert_employee(db, "U_B", "Bob", None)
    _approved_past_leave(db, "U_A", date(2026, 2, 2), date(2026, 2, 2))  # long dry spell
    _approved_past_leave(db, "U_B", date(2026, 5, 29), date(2026, 5, 29))  # short
    signals = ranked_burnout_signals(db, [get_employee(db, "U_B"), get_employee(db, "U_A")], TODAY)
    assert [s.name for s in signals] == ["Alice", "Bob"]  # longest stretch first, not input order
    assert signals[0].stretch > signals[1].stretch


def test_working_stretch_counts_only_elapsed_year_not_future(db):
    # #6: the longest working stretch is measured to *today*, not year-end, so a
    # person with no leave isn't credited with the whole year's future weekdays.
    set_policy(db)
    upsert_employee(db, "U_A", "Alice", None)
    [sig] = ranked_burnout_signals(db, [get_employee(db, "U_A")], TODAY)
    assert sig.working == count_weekdays(date(2026, 1, 1), TODAY)
    assert sig.working < count_weekdays(date(2026, 1, 1), date(2026, 12, 31))  # future excluded


def test_burnout_references_the_leave_period_not_the_calendar_year(db):
    # Leave year resets 13 Apr: a report who has never taken leave has a no-break
    # stretch anchored at the current period start (13 Apr), not 1 Jan, and days-left
    # counts down to the next reset, not 31 Dec.
    set_policy(db, reset_month=4, reset_day=13)
    upsert_employee(db, "U_A", "Alice", None)
    [sig] = ranked_burnout_signals(db, [get_employee(db, "U_A")], TODAY)
    assert sig.stretch == (TODAY - date(2026, 4, 13)).days
    assert sig.days_left == (date(2027, 4, 12) - TODAY).days


def test_stretch_is_zero_while_currently_on_leave(db):
    # #7: a report on approved leave right now is resting, not enduring a run — their
    # no-break stretch reads 0 (least at risk), even though their last *ended* leave
    # was long ago.
    set_policy(db)
    upsert_employee(db, "U_A", "Alice", None)
    _approved_past_leave(db, "U_A", date(2026, 1, 5), date(2026, 1, 5))  # last ended leave, long ago
    on_now = create_request(db, "U_A", "vacation", date(2026, 6, 1), date(2026, 6, 12), None)
    approve_request(db, on_now)  # covers TODAY (2026-06-08)
    [sig] = ranked_burnout_signals(db, [get_employee(db, "U_A")], TODAY)
    assert sig.stretch == 0


def test_manager_sees_direct_reports_ranked_with_explainable_flags(db):
    set_policy(db)
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_A", "Alice", "U_M")
    upsert_employee(db, "U_B", "Bob", "U_M")
    _approved_past_leave(db, "U_A", date(2026, 2, 2), date(2026, 2, 2))
    _approved_past_leave(db, "U_B", date(2026, 5, 29), date(2026, 5, 29))
    client, ack = FakeSlackClient(), FakeAck()

    open_burnout(ack=ack, body=_command("U_M"), db=db, client=client, today=TODAY)

    assert ack.called
    text = _board_text(client)
    assert text.index("Alice") < text.index("Bob")  # longest no-break stretch ranks first
    assert "#1 · Alice" in text and "#2 · Bob" in text  # ranked, most at risk first
    # The board is trimmed to the flags that matter at a glance — and the dot only
    # bands the visible stretch, never an opaque score.
    assert "Days since last leave" in text
    assert "Vacation left" in text
    assert "Next break" in text
    assert "Longest working stretch" not in text  # moved off the board (kept in the CSV)
    assert "Days left in year" not in text
    assert "expiring" not in text.lower()  # forward-looking; /advance owns that


def test_board_opens_a_loading_modal_then_fills_it(db):
    set_policy(db)
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_A", "Alice", "U_M")
    client = FakeSlackClient()

    open_burnout(ack=FakeAck(), body=_command("U_M", trigger_id="Tabc"), db=db, client=client, today=TODAY)

    # An instant placeholder is opened on the trigger_id...
    loading = client.views_open_calls[0]
    assert loading["trigger_id"] == "Tabc"
    assert "Building" in loading["view"]["blocks"][0]["text"]["text"]
    # ...then the real board replaces it, targeting the same external_id.
    assert client.views_update_calls[0]["external_id"] == loading["view"]["external_id"]
    assert "Alice" in _board_text(client)


def test_caller_who_manages_no_one_gets_clear_reply(db):
    set_policy(db)
    upsert_employee(db, "U_SOLO", "Solo", None)  # manages nobody
    client, ack = FakeSlackClient(), FakeAck()

    open_burnout(ack=ack, body=_command("U_SOLO"), db=db, client=client, today=TODAY)

    assert ack.response == NOT_A_MANAGER
    assert client.views_open_calls == []  # no modal opened
    assert client.views_update_calls == []


def test_self_managed_caller_is_not_a_manager(db):
    # Own manager = top of chain; they don't report to themselves, so the board is empty.
    set_policy(db)
    upsert_employee(db, "U_SELF", "Selfie", "U_SELF")
    client, ack = FakeSlackClient(), FakeAck()

    open_burnout(ack=ack, body=_command("U_SELF"), db=db, client=client, today=TODAY)

    assert ack.response == NOT_A_MANAGER
    assert client.views_open_calls == []


def test_board_scoped_to_callers_direct_reports_only(db):
    set_policy(db)
    upsert_employee(db, "U_M1", "ManagerOne", None)
    upsert_employee(db, "U_M2", "ManagerTwo", None)
    upsert_employee(db, "U_A", "Alice", "U_M1")  # ManagerOne's report
    upsert_employee(db, "U_Z", "Zoe", "U_M2")  # ManagerTwo's report
    client = FakeSlackClient()

    open_burnout(ack=FakeAck(), body=_command("U_M1"), db=db, client=client, today=TODAY)

    text = _board_text(client)
    assert "Alice" in text
    assert "Zoe" not in text  # another manager's report never appears


def test_reserved_and_config_items_excluded(db):
    set_policy(db)  # creates the reserved policy item in the employees table
    upsert_holiday(db, date(2026, 12, 31), "New Year's Eve")  # reserved holidays item
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_A", "Alice", "U_M")
    client = FakeSlackClient()

    open_burnout(ack=FakeAck(), body=_command("U_M"), db=db, client=client, today=TODAY)

    # Exactly one report card (Alice); no reserved item leaks onto the board.
    assert len(_nudge_buttons(_board_view(client))) == 1
    text = _board_text(client)
    assert "Alice" in text
    assert "__policy__" not in text and "__holidays__" not in text


def test_report_who_never_took_leave_is_handled(db):
    set_policy(db)
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_A", "Alice", "U_M")  # never took leave
    client = FakeSlackClient()

    open_burnout(ack=FakeAck(), body=_command("U_M"), db=db, client=client, today=TODAY)

    # Stretch measured from a defined start (year start), not an error.
    signals = ranked_burnout_signals(db, [get_employee(db, "U_A")], TODAY)
    assert signals[0].stretch == (TODAY - date(2026, 1, 1)).days
    assert "Alice" in _board_text(client)


def test_nothing_booked_outranks_a_break_already_booked_ahead(db):
    # Two reports who've both gone the same time without leave — but one has a break
    # booked in August (relief coming). The one with nothing booked is the concern,
    # so they rank first; a booked break must not push someone up the risk list.
    set_policy(db)
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_NONE", "Nora", "U_M")  # nothing booked
    upsert_employee(db, "U_BOOKED", "Ben", "U_M")  # a break booked ahead
    create_request(db, "U_BOOKED", "vacation", date(2026, 8, 10), date(2026, 8, 12), None)

    signals = ranked_burnout_signals(
        db, [get_employee(db, "U_BOOKED"), get_employee(db, "U_NONE")], TODAY
    )
    assert signals[0].stretch == signals[1].stretch  # same days since last leave
    assert [s.name for s in signals] == ["Nora", "Ben"]  # nothing booked ranks first


def test_board_shows_next_booked_break_or_nothing(db):
    set_policy(db)
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_BOOKED", "Ben", "U_M")
    upsert_employee(db, "U_NONE", "Nora", "U_M")
    create_request(db, "U_BOOKED", "vacation", date(2026, 8, 12), date(2026, 8, 14), None)
    client = FakeSlackClient()

    open_burnout(ack=FakeAck(), body=_command("U_M"), db=db, client=client, today=TODAY)

    text = _board_text(client)
    assert "Aug 12" in text  # Ben's next booked break, shown as the date
    assert "Nothing booked" in text  # Nora has none ahead


def test_cards_are_separated_by_dividers(db):
    set_policy(db)
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_A", "Alice", "U_M")
    upsert_employee(db, "U_B", "Bob", "U_M")
    client = FakeSlackClient()

    open_burnout(ack=FakeAck(), body=_command("U_M"), db=db, client=client, today=TODAY)

    dividers = [b for b in _board_view(client)["blocks"] if b.get("type") == "divider"]
    assert len(dividers) >= 2  # a separator line per person


def test_board_shows_profile_pictures_when_available(db):
    set_policy(db)
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_A", "Alice", "U_M")
    client = FakeSlackClient()
    client.avatars["U_A"] = "https://example.com/alice.png"  # Slack profile image

    open_burnout(ack=FakeAck(), body=_command("U_M"), db=db, client=client, today=TODAY)

    images = [
        b["accessory"]
        for b in _board_view(client)["blocks"]
        if isinstance(b.get("accessory"), dict) and b["accessory"].get("type") == "image"
    ]
    assert any(img["image_url"] == "https://example.com/alice.png" for img in images)


def test_board_and_csv_compute_the_same_signals(db):
    # The board and the /control burnout CSV share one computation, so a row's
    # numbers must match between them — they cannot drift.
    set_policy(db)
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_A", "Alice", "U_M")
    _approved_past_leave(db, "U_A", date(2026, 2, 2), date(2026, 2, 2))

    board = next(s for s in ranked_burnout_signals(db, [get_employee(db, "U_A")], TODAY) if s.name == "Alice")
    csv_row = next(line for line in build_burnout_csv(db, TODAY).splitlines() if line.startswith("Alice"))
    assert csv_row.split(",") == [
        "Alice",
        str(board.stretch),
        str(board.remaining),
        str(board.days_left),
        str(board.working),
    ]


def test_each_board_row_has_a_nudge_button_targeting_that_person(db):
    set_policy(db)
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_A", "Alice", "U_M")
    upsert_employee(db, "U_B", "Bob", "U_M")
    client = FakeSlackClient()

    open_burnout(ack=FakeAck(), body=_command("U_M"), db=db, client=client, today=TODAY)

    buttons = _nudge_buttons(_board_view(client))
    assert len(buttons) == 2  # one per report
    targets = {json.loads(b["value"])["user_id"] for b in buttons}
    assert targets == {"U_A", "U_B"}  # each button targets its own row's person


def test_refresh_rebuilds_the_open_board(db):
    set_policy(db)
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_A", "Alice", "U_M")
    client, ack = FakeSlackClient(), FakeAck()
    body = {"user": {"id": "U_M"}, "view": {"id": "V1"}}

    refresh_burnout(ack=ack, body=body, client=client, db=db, today=TODAY)

    assert ack.called
    update = client.views_update_calls[-1]
    assert update["view_id"] == "V1"  # rebuilds the same open modal in place
    assert "Alice" in _view_text(update["view"])


# --- Nudge button: bot DM + in-place confirmation, exercised on a board view --------

def _view_with_row(value):
    """A board view shaped like a real row (a name+fields card over an actions block
    carrying the Nudge button) — the surface a click arrives from."""
    return {
        "id": "V1",
        "external_id": "burnout-T",
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "🔴  *#1 · Alice*"},
                "fields": [
                    {"type": "mrkdwn", "text": "*Days since last leave*\n140"},
                    {"type": "mrkdwn", "text": "*Vacation left*\n3 days"},
                ],
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": NUDGE_ACTION,
                        "text": {"type": "plain_text", "text": "🌿 Nudge"},
                        "value": value,
                    }
                ],
            },
        ],
    }


def _nudge_body(value, view, user_id="U_M"):
    return {"actions": [{"value": value}], "user": {"id": user_id}, "view": view}


def test_clicking_nudge_dms_the_report_and_marks_the_row_in_place(db):
    client, ack = FakeSlackClient(), FakeAck()
    value = json.dumps({"user_id": "U_A", "name": "Alice", "stretch": 140, "expiring": 5})

    handle_nudge(ack=ack, body=_nudge_body(value, _view_with_row(value)), client=client)

    assert ack.called
    # The bot DMs the at-risk report — and only them (the manager is not DMed).
    dms = client.chat_postMessage_calls
    assert len(dms) == 1 and dms[0]["channel"] == "U_A"
    dm = dms[0]["text"]
    assert "140 days" in dm  # cites the no-break stretch
    assert "5" in dm and "expire" in dm  # cites the expiring days
    assert "/advance" in dm
    assert "Manager" not in dm and "U_M" not in dm  # bot-voiced, not the manager
    # The manager's confirmation is that row flipping to "Nudged" in place.
    updated = client.views_update_calls[-1]["view"]
    assert "✓ Nudged" in _view_text(updated)
    assert _nudge_buttons(updated) == []  # the button is gone, can't re-fire


def test_nudge_without_expiring_days_still_cites_the_stretch(db):
    client = FakeSlackClient()
    value = json.dumps({"user_id": "U_A", "name": "Alice", "stretch": 90, "expiring": 0})

    handle_nudge(ack=FakeAck(), body=_nudge_body(value, _view_with_row(value)), client=client)

    dm = next(c["text"] for c in client.chat_postMessage_calls if c["channel"] == "U_A")
    assert "90 days" in dm
    assert "/advance" in dm
    assert "expire" not in dm  # nothing expiring → no expiry sentence


def test_nudge_creates_no_leave_request(db):
    client = FakeSlackClient()
    value = json.dumps({"user_id": "U_A", "name": "Alice", "stretch": 140, "expiring": 5})

    handle_nudge(ack=FakeAck(), body=_nudge_body(value, _view_with_row(value)), client=client)

    assert db.requests.scan()["Items"] == []  # a nudge books or modifies nothing
