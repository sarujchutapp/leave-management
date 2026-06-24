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


def test_unregistered_user_gets_contact_admin(db):
    ack = FakeAck()
    open_advance(ack=ack, body={"user_id": "U_NOPE"}, db=db, today=TODAY)
    assert ack.response == CONTACT_ADMIN


def test_caller_with_balance_gets_a_break(db):
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    ack = FakeAck()
    open_advance(ack=ack, body={"user_id": "U_A"}, db=db, today=TODAY)
    text = _option_text(ack.response)
    assert "days off" in text
    assert "Book vacation" in text


def test_top_of_chain_caller_gets_a_result(db):
    # No manager (top of chain) — /advance still suggests a break.
    upsert_employee(db, "U_SOLO", "Solo", None, allowances={"vacation": 5})
    ack = FakeAck()
    open_advance(ack=ack, body={"user_id": "U_SOLO"}, db=db, today=TODAY)
    assert ack.response != ADVANCE_NOTHING
    assert "Book vacation" in _option_text(ack.response)


def test_no_balance_gets_nothing_to_suggest(db):
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 0})
    ack = FakeAck()
    open_advance(ack=ack, body={"user_id": "U_A"}, db=db, today=TODAY)
    assert ack.response == ADVANCE_NOTHING


def test_caller_with_balance_gets_multiple_distinct_options(db):
    # Up to three numbered options, longest-first.
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    ack = FakeAck()
    open_advance(ack=ack, body={"user_id": "U_A"}, db=db, today=TODAY)
    text = _option_text(ack.response)
    assert "*1.*" in text and "*2.*" in text


def test_each_option_has_a_book_button_carrying_its_dates(db):
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    emp = get_employee(db, "U_A")
    breaks = _suggest_breaks(db, emp, TODAY)
    ack = FakeAck()
    open_advance(ack=ack, body={"user_id": "U_A"}, db=db, today=TODAY)
    buttons = _book_buttons(ack.response)
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


def _group_view(selected):
    return {"state": {"values": {"people": {"value": {"selected_users": selected}}}}}


def test_advance_offers_group_break_button(db):
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    ack = FakeAck()
    open_advance(ack=ack, body={"user_id": "U_A"}, db=db, today=TODAY)
    actions = [b for b in ack.response["blocks"] if b.get("type") == "actions"]
    assert any(e["action_id"] == GROUP_PICK_ACTION for b in actions for e in b["elements"])


def test_group_picker_opens_with_people_select(db):
    client = FakeSlackClient()
    ack = FakeAck()
    open_group_picker(ack=ack, body={"user": {"id": "U_A"}, "trigger_id": "T"}, client=client)
    assert ack.called
    view = client.views_open_calls[0]["view"]
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


def test_every_suggested_break_passes_validation(db):
    # The whole point of sourcing inputs from the request flow: every break is
    # bookable. Run each suggestion through validate_request.
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    emp = get_employee(db, "U_A")
    breaks = _suggest_breaks(db, emp, TODAY)
    assert breaks
    for brk in breaks:
        assert validate_request(db, emp, "vacation", brk.book_start, brk.book_end, TODAY) == {}
