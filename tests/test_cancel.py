from datetime import date

from leave.db import get_employee
from leave.handlers import (
    CANNOT_CANCEL,
    NOTHING_TO_CANCEL,
    open_cancel_modal,
    submit_cancel,
)
from leave.requests import (
    approve_request,
    can_cancel,
    create_request,
    decline_request,
    get_request,
    remaining_balance,
    set_calendar_event_id,
    set_ticket_ref,
)
from leave.seed import upsert_employee
from tests.fakes import FakeAck, FakeCalendar, FakeSlackClient, make_cancel_view

TODAY = date(2026, 6, 8)
FUTURE_START = date(2026, 6, 10)
FUTURE_END = date(2026, 6, 11)


def _people(db):
    upsert_employee(db, "U_BOSS", "Boss", None)
    upsert_employee(db, "U_ALICE", "Alice", "U_BOSS")
    upsert_employee(db, "U_BOB", "Bob", "U_BOSS")


def _approved_future(db):
    rid = create_request(db, "U_ALICE", "vacation", FUTURE_START, FUTURE_END, None)
    approve_request(db, rid)
    set_calendar_event_id(db, rid, "evtX")
    return rid


def _status(db, rid):
    return get_request(db, rid)["status"]


def _cancel(db, rid, user, calendar=None, client=None, today=TODAY):
    submit_cancel(
        ack=FakeAck(),
        body={"user": {"id": user}},
        view=make_cancel_view(rid),
        client=client or FakeSlackClient(),
        db=db,
        calendar=calendar or FakeCalendar(),
        today=today,
    )


# --- pure rule -------------------------------------------------------------

def test_can_cancel_rules():
    assert can_cancel({"status": "pending", "start_date": FUTURE_START}, TODAY) is True
    assert can_cancel({"status": "approved", "start_date": FUTURE_START}, TODAY) is True
    assert can_cancel({"status": "approved", "start_date": date(2026, 6, 1)}, TODAY) is False
    assert can_cancel({"status": "declined", "start_date": FUTURE_START}, TODAY) is False


# --- submit_cancel ---------------------------------------------------------

def test_cancel_pending(db):
    _people(db)
    rid = create_request(db, "U_ALICE", "vacation", FUTURE_START, FUTURE_END, None)
    calendar = FakeCalendar()

    _cancel(db, rid, "U_ALICE", calendar=calendar)

    assert _status(db, rid) == "cancelled"
    assert calendar.deleted == []  # nothing on the calendar for a pending request


def test_cancel_pending_withdraws_manager_ticket(db):
    _people(db)
    rid = create_request(db, "U_ALICE", "vacation", FUTURE_START, FUTURE_END, None)
    set_ticket_ref(db, rid, "D1", "9.9")
    client = FakeSlackClient()

    _cancel(db, rid, "U_ALICE", client=client)

    assert _status(db, rid) == "cancelled"
    assert len(client.chat_update_calls) == 1
    assert client.chat_update_calls[0]["channel"] == "D1"
    assert client.chat_update_calls[0]["ts"] == "9.9"


def test_cancel_approved_before_start_deletes_event_and_notifies_manager(db):
    _people(db)
    rid = _approved_future(db)
    client, calendar = FakeSlackClient(), FakeCalendar()

    _cancel(db, rid, "U_ALICE", calendar=calendar, client=client)

    assert _status(db, rid) == "cancelled"
    assert calendar.deleted == ["evtX"]
    assert "U_BOSS" in [c["channel"] for c in client.chat_postMessage_calls]  # manager FYI


def test_cancel_refunds_balance(db):
    _people(db)
    rid = _approved_future(db)
    alice = get_employee(db, "U_ALICE")
    assert remaining_balance(db, alice, "vacation", TODAY) == 8  # Wed-Thu used

    _cancel(db, rid, "U_ALICE")
    assert remaining_balance(db, alice, "vacation", TODAY) == 10


def test_cannot_cancel_approved_after_start(db):
    _people(db)
    rid = create_request(db, "U_ALICE", "vacation", date(2026, 6, 1), date(2026, 6, 2), None)
    approve_request(db, rid)
    client = FakeSlackClient()

    _cancel(db, rid, "U_ALICE", client=client)

    assert _status(db, rid) == "approved"
    assert client.chat_postMessage_calls[0]["text"] == CANNOT_CANCEL


def test_other_user_cannot_cancel(db):
    _people(db)
    rid = create_request(db, "U_ALICE", "vacation", FUTURE_START, FUTURE_END, None)

    _cancel(db, rid, "U_BOB")

    assert _status(db, rid) == "pending"


# --- open_cancel_modal -----------------------------------------------------

def test_cancel_modal_lists_pending_and_future_approved_only(db):
    _people(db)
    pending = create_request(db, "U_ALICE", "sick", FUTURE_START, FUTURE_END, None)
    approved_future = _approved_future(db)
    past = create_request(db, "U_ALICE", "vacation", date(2026, 6, 1), date(2026, 6, 2), None)
    approve_request(db, past)
    declined = create_request(db, "U_ALICE", "personal", FUTURE_START, FUTURE_END, None)
    decline_request(db, declined, None)

    client, ack = FakeSlackClient(), FakeAck()
    open_cancel_modal(
        ack=ack, body={"user_id": "U_ALICE", "trigger_id": "T"}, client=client, db=db, today=TODAY
    )

    assert ack.response is None
    view = client.views_open_calls[0]["view"]
    options = view["blocks"][0]["element"]["options"]
    assert view["blocks"][0]["element"]["type"] == "static_select"
    assert {o["value"] for o in options} == {str(pending), str(approved_future)}


def test_cancel_modal_handles_more_than_ten_requests(db):
    # A backlog of >10 cancellable requests must still render (radio_buttons caps at
    # 10; static_select does not) so /dayoff-cancel doesn't fail to open.
    _people(db)
    for i in range(12):
        create_request(db, "U_ALICE", "vacation", date(2026, 7, i + 1), date(2026, 7, i + 1), None)

    client, ack = FakeSlackClient(), FakeAck()
    open_cancel_modal(
        ack=ack, body={"user_id": "U_ALICE", "trigger_id": "T"}, client=client, db=db, today=TODAY
    )

    element = client.views_open_calls[0]["view"]["blocks"][0]["element"]
    assert element["type"] == "static_select"
    assert len(element["options"]) == 12


def test_cancel_modal_empty(db):
    _people(db)
    client, ack = FakeSlackClient(), FakeAck()
    open_cancel_modal(
        ack=ack, body={"user_id": "U_ALICE", "trigger_id": "T"}, client=client, db=db, today=TODAY
    )
    assert ack.response == NOTHING_TO_CANCEL
    assert client.views_open_calls == []
