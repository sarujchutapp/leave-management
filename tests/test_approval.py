import json
from datetime import date

from leave.handlers import (
    handle_approve,
    handle_decline_click,
    handle_decline_submit,
)
from leave.requests import create_request
from leave.seed import upsert_employee
from tests.fakes import (
    FakeAck,
    FakeCalendar,
    FakeSlackClient,
    make_action_body,
    make_decline_view,
)


def _setup(conn):
    upsert_employee(conn, "U_BOSS", "Boss", None)
    upsert_employee(conn, "U_ALICE", "Alice", "U_BOSS")
    upsert_employee(conn, "U_BOB", "Bob", "U_BOSS")
    return create_request(conn, "U_ALICE", "vacation", date(2026, 6, 10), date(2026, 6, 11), "trip")


def _status(conn, rid):
    return conn.execute("SELECT status FROM requests WHERE id=%s", (rid,)).fetchone()["status"]


def test_manager_approves(conn):
    rid = _setup(conn)
    client = FakeSlackClient()
    calendar = FakeCalendar()

    handle_approve(
        ack=FakeAck(), body=make_action_body(rid, "U_BOSS"), client=client, conn=conn, calendar=calendar
    )

    assert _status(conn, rid) == "approved"
    # ticket updated + employee notified
    assert len(client.chat_postMessage_calls) == 1
    assert client.chat_postMessage_calls[0]["channel"] == "U_ALICE"
    assert len(client.chat_update_calls) == 1
    # calendar event created and stored
    assert len(calendar.created) == 1
    stored = conn.execute(
        "SELECT calendar_event_id FROM requests WHERE id=%s", (rid,)
    ).fetchone()["calendar_event_id"]
    assert stored == calendar.created[0]["id"]


def test_non_manager_cannot_approve(conn):
    rid = _setup(conn)
    client = FakeSlackClient()
    calendar = FakeCalendar()

    handle_approve(
        ack=FakeAck(), body=make_action_body(rid, "U_BOB"), client=client, conn=conn, calendar=calendar
    )

    assert _status(conn, rid) == "pending"
    # the imposter gets told off; the employee is NOT notified
    assert client.chat_postMessage_calls[0]["channel"] == "U_BOB"
    assert client.chat_update_calls == []
    assert calendar.created == []


def test_decline_click_opens_modal_with_metadata(conn):
    rid = _setup(conn)
    client = FakeSlackClient()

    handle_decline_click(
        ack=FakeAck(),
        body=make_action_body(rid, "U_BOSS", channel="C9", ts="222.2"),
        client=client,
        conn=conn,
    )

    assert len(client.views_open_calls) == 1
    meta = json.loads(client.views_open_calls[0]["view"]["private_metadata"])
    assert meta["request_id"] == str(rid)
    assert meta["channel"] == "C9"
    assert meta["ts"] == "222.2"


def test_decline_submit_sets_status_and_notifies_with_reason(conn):
    rid = _setup(conn)
    client = FakeSlackClient()
    meta = json.dumps({"request_id": str(rid), "channel": "C9", "ts": "222.2"})
    view = make_decline_view(meta, reason="too busy")

    handle_decline_submit(
        ack=FakeAck(), body={"user": {"id": "U_BOSS"}}, view=view, client=client, conn=conn
    )

    row = conn.execute("SELECT status, decline_reason FROM requests WHERE id=%s", (rid,)).fetchone()
    assert row["status"] == "declined"
    assert row["decline_reason"] == "too busy"
    notice = client.chat_postMessage_calls[0]
    assert notice["channel"] == "U_ALICE"
    assert "too busy" in notice["text"]


def test_cannot_approve_cancelled_request(conn):
    rid = _setup(conn)
    conn.execute("UPDATE requests SET status='cancelled' WHERE id=%s", (rid,))
    client, calendar = FakeSlackClient(), FakeCalendar()

    handle_approve(
        ack=FakeAck(), body=make_action_body(rid, "U_BOSS"), client=client, conn=conn, calendar=calendar
    )

    assert _status(conn, rid) == "cancelled"  # not flipped back to approved
    assert calendar.created == []  # no calendar event
    assert client.chat_postMessage_calls == []  # employee not notified
    assert len(client.chat_update_calls) == 1  # stale ticket closed


def test_cannot_double_approve(conn):
    rid = _setup(conn)
    calendar = FakeCalendar()
    body = make_action_body(rid, "U_BOSS")

    handle_approve(ack=FakeAck(), body=body, client=FakeSlackClient(), conn=conn, calendar=calendar)
    handle_approve(ack=FakeAck(), body=body, client=FakeSlackClient(), conn=conn, calendar=calendar)

    assert _status(conn, rid) == "approved"
    assert len(calendar.created) == 1  # second click creates no second event


def test_cannot_decline_cancelled_request(conn):
    rid = _setup(conn)
    conn.execute("UPDATE requests SET status='cancelled' WHERE id=%s", (rid,))
    client = FakeSlackClient()
    meta = json.dumps({"request_id": str(rid), "channel": "C9", "ts": "222.2"})

    handle_decline_submit(
        ack=FakeAck(), body={"user": {"id": "U_BOSS"}}, view=make_decline_view(meta, "no"),
        client=client, conn=conn,
    )

    assert _status(conn, rid) == "cancelled"  # not flipped to declined
    assert len(client.chat_update_calls) == 1  # stale ticket closed


def test_non_manager_cannot_decline(conn):
    rid = _setup(conn)
    client = FakeSlackClient()
    meta = json.dumps({"request_id": str(rid), "channel": "C9", "ts": "222.2"})
    view = make_decline_view(meta, reason="nope")

    handle_decline_submit(
        ack=FakeAck(), body={"user": {"id": "U_BOB"}}, view=view, client=client, conn=conn
    )

    assert _status(conn, rid) == "pending"
    assert client.chat_postMessage_calls == []
