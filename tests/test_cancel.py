from datetime import date

from leave.db import get_employee
from leave.handlers import (
    CANNOT_CANCEL,
    NOTHING_TO_CANCEL,
    open_cancel_modal,
    submit_cancel,
)
from leave.requests import can_cancel, create_request, remaining_balance
from leave.seed import upsert_employee
from tests.fakes import FakeAck, FakeCalendar, FakeSlackClient, make_cancel_view

TODAY = date(2026, 6, 8)
FUTURE_START = date(2026, 6, 10)
FUTURE_END = date(2026, 6, 11)


def _people(conn):
    upsert_employee(conn, "U_BOSS", "Boss", None)
    upsert_employee(conn, "U_ALICE", "Alice", "U_BOSS")
    upsert_employee(conn, "U_BOB", "Bob", "U_BOSS")


def _approved_future(conn):
    rid = create_request(conn, "U_ALICE", "vacation", FUTURE_START, FUTURE_END, None)
    conn.execute(
        "UPDATE requests SET status='approved', calendar_event_id='evtX' WHERE id=%s", (rid,)
    )
    return rid


def _status(conn, rid):
    return conn.execute("SELECT status FROM requests WHERE id=%s", (rid,)).fetchone()["status"]


def _cancel(conn, rid, user, calendar=None, client=None, today=TODAY):
    submit_cancel(
        ack=FakeAck(),
        body={"user": {"id": user}},
        view=make_cancel_view(rid),
        client=client or FakeSlackClient(),
        conn=conn,
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

def test_cancel_pending(conn):
    _people(conn)
    rid = create_request(conn, "U_ALICE", "vacation", FUTURE_START, FUTURE_END, None)
    calendar = FakeCalendar()

    _cancel(conn, rid, "U_ALICE", calendar=calendar)

    assert _status(conn, rid) == "cancelled"
    assert calendar.deleted == []  # nothing on the calendar for a pending request


def test_cancel_approved_before_start_deletes_event_and_notifies_manager(conn):
    _people(conn)
    rid = _approved_future(conn)
    client, calendar = FakeSlackClient(), FakeCalendar()

    _cancel(conn, rid, "U_ALICE", calendar=calendar, client=client)

    assert _status(conn, rid) == "cancelled"
    assert calendar.deleted == ["evtX"]
    assert "U_BOSS" in [c["channel"] for c in client.chat_postMessage_calls]  # manager FYI


def test_cancel_refunds_balance(conn):
    _people(conn)
    rid = _approved_future(conn)
    alice = get_employee(conn, "U_ALICE")
    assert remaining_balance(conn, alice, "vacation", TODAY) == 8  # Wed-Thu used

    _cancel(conn, rid, "U_ALICE")
    assert remaining_balance(conn, alice, "vacation", TODAY) == 10


def test_cannot_cancel_approved_after_start(conn):
    _people(conn)
    rid = create_request(conn, "U_ALICE", "vacation", date(2026, 6, 1), date(2026, 6, 2), None)
    conn.execute("UPDATE requests SET status='approved' WHERE id=%s", (rid,))
    client = FakeSlackClient()

    _cancel(conn, rid, "U_ALICE", client=client)

    assert _status(conn, rid) == "approved"
    assert client.chat_postMessage_calls[0]["text"] == CANNOT_CANCEL


def test_other_user_cannot_cancel(conn):
    _people(conn)
    rid = create_request(conn, "U_ALICE", "vacation", FUTURE_START, FUTURE_END, None)

    _cancel(conn, rid, "U_BOB")

    assert _status(conn, rid) == "pending"


# --- open_cancel_modal -----------------------------------------------------

def test_cancel_modal_lists_pending_and_future_approved_only(conn):
    _people(conn)
    pending = create_request(conn, "U_ALICE", "sick", FUTURE_START, FUTURE_END, None)
    approved_future = _approved_future(conn)
    past = create_request(conn, "U_ALICE", "vacation", date(2026, 6, 1), date(2026, 6, 2), None)
    conn.execute("UPDATE requests SET status='approved' WHERE id=%s", (past,))
    declined = create_request(conn, "U_ALICE", "personal", FUTURE_START, FUTURE_END, None)
    conn.execute("UPDATE requests SET status='declined' WHERE id=%s", (declined,))

    client, ack = FakeSlackClient(), FakeAck()
    open_cancel_modal(ack=ack, body={"user_id": "U_ALICE", "trigger_id": "T"}, client=client, conn=conn, today=TODAY)

    assert ack.response is None
    view = client.views_open_calls[0]["view"]
    options = view["blocks"][0]["element"]["options"]
    assert {o["value"] for o in options} == {str(pending), str(approved_future)}


def test_cancel_modal_empty(conn):
    _people(conn)
    client, ack = FakeSlackClient(), FakeAck()
    open_cancel_modal(ack=ack, body={"user_id": "U_ALICE", "trigger_id": "T"}, client=client, conn=conn, today=TODAY)
    assert ack.response == NOTHING_TO_CANCEL
    assert client.views_open_calls == []
