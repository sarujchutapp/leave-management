"""Handler-seam tests for /advance (the longest-break tracer + Book button). The
optimizer math is covered directly in test_optimizer.py; here we test the gather,
the rendered options, and the prefilled apply modal the Book button opens."""

from datetime import date

from leave.blocks import ADVANCE_BOOK_ACTION, GROUP_CALLBACK_ID, GROUP_PICK_ACTION, LEAVE_CALLBACK_ID
from leave.db import get_employee
from leave.handlers import (
    ADVANCE_NOTHING,
    CONTACT_ADMIN,
    GROUP_NO_WINDOW,
    _suggest_breaks,
    open_advance,
    open_book_modal,
    open_group_picker,
    submit_group_break,
)
from leave.policy import set_policy
from leave.requests import create_request
from leave.seed import upsert_employee
from leave.validation import validate_request
from tests.fakes import FakeAck, FakeSlackClient, make_action_body

TODAY = date(2026, 6, 8)  # a Monday


def _option_text(response):
    """All section text from a blocks /advance reply, joined."""
    return "\n".join(
        b["text"]["text"] for b in response["blocks"] if b.get("type") == "section"
    )


def _book_buttons(response):
    return [
        b["accessory"]
        for b in response["blocks"]
        if b.get("accessory", {}).get("action_id") == ADVANCE_BOOK_ACTION
    ]


def _block_element(view, block_id):
    return next(b for b in view["blocks"] if b.get("block_id") == block_id)["element"]


def _modal_section_text(view):
    return "\n".join(
        b["text"]["text"] for b in view["blocks"] if b.get("type") == "section"
    )


def test_advance_opens_modal_with_options_and_buttons(db):
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    client = FakeSlackClient()
    ack = FakeAck()
    open_advance(ack=ack, body={"user_id": "U_A", "trigger_id": "T"}, client=client, db=db, today=TODAY)
    assert ack.called
    view = client.views_open_calls[0]["view"]
    assert view["type"] == "modal"
    assert "days off" in _modal_section_text(view)
    book = [
        b["accessory"]
        for b in view["blocks"]
        if b.get("accessory", {}).get("action_id") == ADVANCE_BOOK_ACTION
    ]
    assert book
    actions = [e for b in view["blocks"] if b.get("type") == "actions" for e in b["elements"]]
    assert any(e["action_id"] == GROUP_PICK_ACTION for e in actions)


def test_option_line_shows_length_quota_and_short_date(db):
    # Compact for the small modal: days-off length, quota used, and the booking dates
    # in a short form (e.g. "Jun 8–12") — not the long ISO range.
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    text = _option_text(_advance_view(db, "U_A", FakeSlackClient()))
    assert "days off" in text and "used" in text
    assert "Jun" in text  # short month booking date
    assert "2026-" not in text  # not the long ISO form


def test_unregistered_user_gets_contact_admin(db):
    ack = FakeAck()
    open_advance(
        ack=ack, body={"user_id": "U_NOPE", "trigger_id": "T"}, client=FakeSlackClient(), db=db, today=TODAY
    )
    assert ack.response == CONTACT_ADMIN


def _advance_view(db, user_id, client):
    open_advance(
        ack=FakeAck(), body={"user_id": user_id, "trigger_id": "T"}, client=client, db=db, today=TODAY
    )
    return client.views_open_calls[0]["view"]


def test_caller_with_balance_gets_a_break(db):
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    text = _option_text(_advance_view(db, "U_A", FakeSlackClient()))
    assert "days off" in text
    assert "used" in text


def test_top_of_chain_caller_gets_a_result(db):
    # No manager (top of chain) — /advance still suggests a break.
    upsert_employee(db, "U_SOLO", "Solo", None, allowances={"vacation": 5})
    text = _option_text(_advance_view(db, "U_SOLO", FakeSlackClient()))
    assert ADVANCE_NOTHING not in text
    assert "days off" in text


def test_no_balance_shows_nothing_to_suggest(db):
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 0})
    text = _option_text(_advance_view(db, "U_A", FakeSlackClient()))
    assert text == ADVANCE_NOTHING


def test_pending_only_balance_note_mentions_awaiting_approval(db):
    # All balance tied up in a pending request → free balance 0 → nothing to suggest.
    # Since the optimizer now plans against free days, "awaiting approval" is a real
    # cause, so the single note must own it (not just "out of balance").
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    create_request(db, "U_A", "vacation", date(2026, 7, 6), date(2026, 7, 10), "trip")
    text = _option_text(_advance_view(db, "U_A", FakeSlackClient()))
    assert "approval" in text.lower()


def test_caller_with_balance_gets_multiple_distinct_options(db):
    # Up to three numbered options, longest-first.
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    text = _option_text(_advance_view(db, "U_A", FakeSlackClient()))
    assert "*1.*" in text and "*2.*" in text


def test_each_option_has_a_book_button_carrying_its_dates(db):
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    emp = get_employee(db, "U_A")
    breaks = _suggest_breaks(db, emp, TODAY)
    buttons = _book_buttons(_advance_view(db, "U_A", FakeSlackClient()))
    assert len(buttons) == len(breaks)
    # The first button carries the first break's start|end dates.
    first = breaks[0]
    assert buttons[0]["value"] == f"{first.book_start.isoformat()}|{first.book_end.isoformat()}"


def test_book_button_opens_prefilled_apply_modal(db):
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    client = FakeSlackClient()
    ack = FakeAck()
    body = make_action_body("2026-06-01|2026-06-05", "U_A")
    open_book_modal(ack=ack, body=body, client=client, db=db, today=TODAY)
    assert ack.called
    view = client.views_open_calls[0]["view"]
    assert view["callback_id"] == LEAVE_CALLBACK_ID
    # Dates pre-filled, leave type defaulted to vacation (a break is vacation-only).
    assert _block_element(view, "start_date")["initial_date"] == "2026-06-01"
    assert _block_element(view, "end_date")["initial_date"] == "2026-06-05"
    assert _block_element(view, "leave_type")["initial_option"]["value"] == "vacation"


def test_book_from_modal_pushes_apply_modal(db):
    # Clicked inside the /advance modal (body carries a "view"), so the apply modal
    # is pushed onto the stack, not opened as a fresh root.
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    client = FakeSlackClient()
    body = make_action_body("2026-06-01|2026-06-05", "U_A")
    body["view"] = {"id": "V1"}
    open_book_modal(ack=FakeAck(), body=body, client=client, db=db, today=TODAY)
    assert not client.views_open_calls
    assert client.views_push_calls[0]["view"]["callback_id"] == LEAVE_CALLBACK_ID


def _group_view(selected):
    return {"state": {"values": {"people": {"value": {"selected_users": selected}}}}}


def test_advance_offers_group_break_button(db):
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    view = _advance_view(db, "U_A", FakeSlackClient())
    actions = [b for b in view["blocks"] if b.get("type") == "actions"]
    assert any(e["action_id"] == GROUP_PICK_ACTION for b in actions for e in b["elements"])


def test_group_picker_pushes_from_advance_modal(db):
    # The button lives inside the /advance modal (body carries a "view"), so the
    # picker must be pushed onto the stack — views_open is ignored mid-modal.
    client = FakeSlackClient()
    ack = FakeAck()
    open_group_picker(
        ack=ack, body={"user": {"id": "U_A"}, "trigger_id": "T", "view": {"id": "V1"}}, client=client
    )
    assert ack.called
    assert not client.views_open_calls
    view = client.views_push_calls[0]["view"]
    assert view["callback_id"] == GROUP_CALLBACK_ID
    people = next(b for b in view["blocks"] if b.get("block_id") == "people")
    assert people["element"]["type"] == "multi_users_select"


def test_group_break_submit_dms_shared_window(db):
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    upsert_employee(db, "U_B", "Bob", None, allowances={"vacation": 5})
    client = FakeSlackClient()
    ack = FakeAck()
    submit_group_break(
        ack=ack,
        body={"user": {"id": "U_A"}},
        view=_group_view(["U_B"]),
        client=client,
        db=db,
        today=date(2026, 6, 8),
    )
    assert ack.called
    dm = client.chat_postMessage_calls[0]
    assert dm["channel"] == "U_A"  # DM'd to the caller
    assert "off together" in dm["text"]
    assert " to 2026-" in dm["text"]  # a concrete shared window
    # Privacy: only the window — no balances or per-person detail.
    assert "balance" not in dm["text"].lower()
    assert "Bob" not in dm["text"] and "Alice" not in dm["text"]


def test_group_result_has_book_mine_button_for_caller(db):
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    upsert_employee(db, "U_B", "Bob", None, allowances={"vacation": 5})
    client = FakeSlackClient()
    submit_group_break(
        ack=FakeAck(),
        body={"user": {"id": "U_A"}},
        view=_group_view(["U_B"]),
        client=client,
        db=db,
        today=date(2026, 6, 8),
    )
    dm = client.chat_postMessage_calls[0]
    # Shareable text stays so teammates can coordinate and book themselves.
    assert "off together" in dm["text"]
    # A "Book mine" button reuses the prefilled-apply-modal mechanism (ADVANCE_BOOK_ACTION).
    buttons = [
        e
        for b in dm.get("blocks", [])
        if b.get("type") == "actions"
        for e in b["elements"]
    ]
    book = [e for e in buttons if e["action_id"] == ADVANCE_BOOK_ACTION]
    assert len(book) == 1
    assert book[0]["text"]["text"] == "Book mine"
    start, end = book[0]["value"].split("|")
    assert start in dm["text"] and end in dm["text"]  # the shared window dates


def _group_window(dm):
    button = next(
        e
        for b in dm.get("blocks", [])
        if b.get("type") == "actions"
        for e in b["elements"]
    )
    start, end = button["value"].split("|")
    return date.fromisoformat(start), date.fromisoformat(end)


def test_group_window_excludes_callers_half_day(db):
    # The caller holds a half-day on Wed 06-17 — blocked-but-present — so the shared
    # all-off window the group finder DMs must not cover that date.
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    upsert_employee(db, "U_B", "Bob", None, allowances={"vacation": 5})
    create_request(db, "U_A", "vacation", date(2026, 6, 17), date(2026, 6, 17), "appt", half="morning")
    client = FakeSlackClient()
    submit_group_break(
        ack=FakeAck(),
        body={"user": {"id": "U_A"}},
        view=_group_view(["U_B"]),
        client=client,
        db=db,
        today=date(2026, 6, 8),
    )
    start, end = _group_window(client.chat_postMessage_calls[0])
    assert not (start <= date(2026, 6, 17) <= end)


def test_group_break_rejects_bot_pick(db):
    # The user-picker can't hide apps/bots, so a bot pick is rejected on submit with
    # an inline error on the people field — and no window is computed or DM'd.
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    client = FakeSlackClient()
    client.bot_users.add("U_BOT")
    ack = FakeAck()
    submit_group_break(
        ack=ack,
        body={"user": {"id": "U_A"}},
        view=_group_view(["U_BOT"]),
        client=client,
        db=db,
        today=date(2026, 6, 8),
    )
    assert ack.response["response_action"] == "errors"
    assert "people" in ack.response["errors"]
    assert not client.chat_postMessage_calls


def test_group_break_submit_reports_no_common_window(db):
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    upsert_employee(db, "U_B", "Bob", None, allowances={"vacation": 0})  # can't be off
    client = FakeSlackClient()
    submit_group_break(
        ack=FakeAck(),
        body={"user": {"id": "U_A"}},
        view=_group_view(["U_B"]),
        client=client,
        db=db,
        today=date(2026, 6, 8),
    )
    assert client.chat_postMessage_calls[0]["text"] == GROUP_NO_WINDOW


def test_pending_half_day_is_never_inside_a_suggestion(db):
    # A half-day on Wed 06-17 is blocked-but-present: no suggested booking may cover
    # it, or it would overlap the half-day at submit (active_full_leave_ranges hides
    # half-days from the optimizer, so the handler must feed them as blocked dates).
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    create_request(db, "U_A", "vacation", date(2026, 6, 17), date(2026, 6, 17), "appt", half="morning")
    emp = get_employee(db, "U_A")
    breaks = _suggest_breaks(db, emp, TODAY)
    assert breaks
    for brk in breaks:
        assert not (brk.book_start <= date(2026, 6, 17) <= brk.book_end)


def test_pending_vacation_shrinks_suggestions_to_free_days(db):
    # 3 pending (not yet approved) vacation days far from June. remaining_balance
    # still reads 5 (approved-only), but only 2 days are truly free to book, so no
    # suggested break may cost more than 2.
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    create_request(db, "U_A", "vacation", date(2026, 9, 7), date(2026, 9, 9), "trip")
    emp = get_employee(db, "U_A")
    breaks = _suggest_breaks(db, emp, TODAY)
    assert breaks
    assert max(brk.cost for brk in breaks) <= 2


def test_suggestions_are_bounded_by_the_next_reset_not_dec_31(db):
    # Leave year resets 1 Jul: on 8 Jun the current period ends 30 Jun, so no
    # suggested break may book a day on or after the next reset — even with a balance
    # big enough to otherwise reach deep into the calendar year.
    set_policy(db, reset_month=7, reset_day=1)
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 20})
    emp = get_employee(db, "U_A")
    breaks = _suggest_breaks(db, emp, TODAY)
    assert breaks
    for brk in breaks:
        assert brk.book_end < date(2026, 7, 1)


def test_group_window_is_bounded_by_the_next_reset(db):
    # The group-break finder shares the same horizon: a shared window can't run past
    # the next reset (1 Jul here), not 31 Dec.
    set_policy(db, reset_month=7, reset_day=1)
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 20})
    upsert_employee(db, "U_B", "Bob", None, allowances={"vacation": 20})
    client = FakeSlackClient()
    submit_group_break(
        ack=FakeAck(),
        body={"user": {"id": "U_A"}},
        view=_group_view(["U_B"]),
        client=client,
        db=db,
        today=TODAY,
    )
    _, end = _group_window(client.chat_postMessage_calls[0])
    assert end < date(2026, 7, 1)


def test_every_suggested_break_passes_validation(db):
    # The whole point of sourcing inputs from the request flow: every break is
    # bookable. Run each suggestion through validate_request.
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    emp = get_employee(db, "U_A")
    breaks = _suggest_breaks(db, emp, TODAY)
    assert breaks
    for brk in breaks:
        assert validate_request(db, emp, "vacation", brk.book_start, brk.book_end, TODAY) == {}


def test_suggestions_pass_validation_with_pending_leave(db):
    # The half-day (06-17) and a pending full-day range must not produce a suggestion
    # that validate_request rejects — has_overlap sees pending + half-day leave the
    # optimizer's full-day ranges hide, so the blocked-date wiring is what keeps the
    # promise.
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 10})
    create_request(db, "U_A", "vacation", date(2026, 6, 17), date(2026, 6, 17), "appt", half="morning")
    create_request(db, "U_A", "vacation", date(2026, 9, 7), date(2026, 9, 9), "trip")
    emp = get_employee(db, "U_A")
    breaks = _suggest_breaks(db, emp, TODAY)
    assert breaks
    for brk in breaks:
        assert validate_request(db, emp, "vacation", brk.book_start, brk.book_end, TODAY) == {}
