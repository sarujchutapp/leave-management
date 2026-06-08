from datetime import date

from leave.handlers import CANNOT_CANCEL, NOTHING_TO_CANCEL, handle_cancel, open_cancel_list
from leave.requests import can_cancel, create_request, remaining_balance
from leave.seed import upsert_employee
from leave.db import get_employee
from tests.fakes import FakeAck, FakeCalendar, FakeSlackClient, make_action_body

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


# --- pure rule -------------------------------------------------------------

def test_can_cancel_rules():
    assert can_cancel({"status": "pending", "start_date": FUTURE_START}, TODAY) is True
    assert can_cancel({"status": "approved", "start_date": FUTURE_START}, TODAY) is True
    # approved but already started
    assert can_cancel({"status": "approved", "start_date": date(2026, 6, 1)}, TODAY) is False
    assert can_cancel({"status": "declined", "start_date": FUTURE_START}, TODAY) is False


# --- cancel a pending request ----------------------------------------------

def test_cancel_pending(conn):
    _people(conn)
    rid = create_request(conn, "U_ALICE", "vacation", FUTURE_START, FUTURE_END, None)
    client, calendar = FakeSlackClient(), FakeCalendar()

    handle_cancel(
        ack=FakeAck(), body=make_action_body(rid, "U_ALICE"), client=client, conn=conn,
        calendar=calendar, today=TODAY,
    )

    assert _status(conn, rid) == "cancelled"
    assert calendar.deleted == []  # nothing on the calendar for a pending request


# --- cancel an approved future request -------------------------------------

def test_cancel_approved_before_start_deletes_event_and_notifies_manager(conn):
    _people(conn)
    rid = _approved_future(conn)
    client, calendar = FakeSlackClient(), FakeCalendar()

    handle_cancel(
        ack=FakeAck(), body=make_action_body(rid, "U_ALICE"), client=client, conn=conn,
        calendar=calendar, today=TODAY,
    )

    assert _status(conn, rid) == "cancelled"
    assert calendar.deleted == ["evtX"]
    channels = [c["channel"] for c in client.chat_postMessage_calls]
    assert "U_BOSS" in channels  # manager FYI


def test_cancel_refunds_balance(conn):
    _people(conn)
    rid = _approved_future(conn)
    alice = get_employee(conn, "U_ALICE")
    # Wed-Thu approved = 2 days used
    assert remaining_balance(conn, alice, "vacation", TODAY) == 8

    handle_cancel(
        ack=FakeAck(), body=make_action_body(rid, "U_ALICE"), client=FakeSlackClient(), conn=conn,
        calendar=FakeCalendar(), today=TODAY,
    )
    assert remaining_balance(conn, alice, "vacation", TODAY) == 10


# --- guards ----------------------------------------------------------------

def test_cannot_cancel_approved_after_start(conn):
    _people(conn)
    rid = create_request(conn, "U_ALICE", "vacation", date(2026, 6, 1), date(2026, 6, 2), None)
    conn.execute("UPDATE requests SET status='approved' WHERE id=%s", (rid,))
    client = FakeSlackClient()

    handle_cancel(
        ack=FakeAck(), body=make_action_body(rid, "U_ALICE"), client=client, conn=conn,
        calendar=FakeCalendar(), today=TODAY,
    )

    assert _status(conn, rid) == "approved"
    assert client.chat_postMessage_calls[0]["text"] == CANNOT_CANCEL


def test_other_user_cannot_cancel(conn):
    _people(conn)
    rid = create_request(conn, "U_ALICE", "vacation", FUTURE_START, FUTURE_END, None)

    handle_cancel(
        ack=FakeAck(), body=make_action_body(rid, "U_BOB"), client=FakeSlackClient(), conn=conn,
        calendar=FakeCalendar(), today=TODAY,
    )

    assert _status(conn, rid) == "pending"


# --- listing ---------------------------------------------------------------

def test_cancel_list_shows_pending_and_future_approved_only(conn):
    _people(conn)
    pending = create_request(conn, "U_ALICE", "sick", FUTURE_START, FUTURE_END, None)
    approved_future = _approved_future(conn)
    # approved past + declined should not appear
    past = create_request(conn, "U_ALICE", "vacation", date(2026, 6, 1), date(2026, 6, 2), None)
    conn.execute("UPDATE requests SET status='approved' WHERE id=%s", (past,))
    declined = create_request(conn, "U_ALICE", "personal", FUTURE_START, FUTURE_END, None)
    conn.execute("UPDATE requests SET status='declined' WHERE id=%s", (declined,))

    ack = FakeAck()
    open_cancel_list(ack=ack, body={"user_id": "U_ALICE"}, conn=conn, today=TODAY)

    values = {b["accessory"]["value"] for b in ack.response["blocks"]}
    assert values == {str(pending), str(approved_future)}


def test_cancel_list_empty(conn):
    _people(conn)
    ack = FakeAck()
    open_cancel_list(ack=ack, body={"user_id": "U_ALICE"}, conn=conn, today=TODAY)
    assert ack.response == NOTHING_TO_CANCEL
