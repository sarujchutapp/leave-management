from datetime import date

from leave.blocks import LEAVE_CALLBACK_ID, LEAVE_TYPES
from leave.handlers import CONTACT_ADMIN, open_leave_modal, submit_leave
from leave.seed import upsert_employee
from tests.fakes import FakeAck, FakeCalendar, FakeSlackClient, make_leave_view

TODAY = date(2026, 6, 8)


def _block_by_id(view, block_id):
    return next(b for b in view["blocks"] if b.get("block_id") == block_id)


def test_registered_user_opens_modal_with_balances(db):
    upsert_employee(db, "U_ALICE", "Alice", None)
    client = FakeSlackClient()
    ack = FakeAck()

    open_leave_modal(
        ack=ack,
        body={"user_id": "U_ALICE", "trigger_id": "T123"},
        client=client,
        db=db,
        today=TODAY,
    )

    assert ack.called and ack.response is None
    assert len(client.views_open_calls) == 1
    view = client.views_open_calls[0]["view"]
    assert view["callback_id"] == LEAVE_CALLBACK_ID

    type_block = _block_by_id(view, "leave_type")
    assert [o["value"] for o in type_block["element"]["options"]] == LEAVE_TYPES
    # balance context line is present
    assert any(b["type"] == "context" for b in view["blocks"])


def test_unregistered_user_gets_contact_admin(db):
    client = FakeSlackClient()
    ack = FakeAck()

    open_leave_modal(
        ack=ack, body={"user_id": "U_NOPE", "trigger_id": "T"}, client=client, db=db, today=TODAY
    )

    assert ack.response == CONTACT_ADMIN
    assert client.views_open_calls == []


def test_submit_valid_persists_pending_and_dms_manager(db):
    upsert_employee(db, "U_BOSS", "Boss", None)
    upsert_employee(db, "U_ALICE", "Alice", "U_BOSS")
    ack = FakeAck()
    client = FakeSlackClient()
    calendar = FakeCalendar()
    view = make_leave_view("vacation", "2026-06-10", "2026-06-11", "trip")

    submit_leave(
        ack=ack,
        body={"user": {"id": "U_ALICE"}},
        view=view,
        client=client,
        db=db,
        calendar=calendar,
        today=TODAY,
    )

    assert ack.called and ack.response is None
    row = db.execute(
        "SELECT status, reason, ticket_ts FROM requests WHERE employee_id='U_ALICE'"
    ).fetchone()
    assert row["status"] == "pending"
    assert row["reason"] == "trip"
    # ticket DM'd to the manager
    assert len(client.chat_postMessage_calls) == 1
    assert client.chat_postMessage_calls[0]["channel"] == "U_BOSS"
    # the ticket message reference is stored for later withdrawal
    assert row["ticket_ts"] is not None
    # pending request -> no calendar event
    assert calendar.created == []


def test_submit_auto_approves_when_no_manager(db):
    upsert_employee(db, "U_SOLO", "Solo", None)  # no manager
    ack = FakeAck()
    client = FakeSlackClient()
    calendar = FakeCalendar()
    view = make_leave_view("vacation", "2026-06-10", "2026-06-11")

    submit_leave(
        ack=ack,
        body={"user": {"id": "U_SOLO"}},
        view=view,
        client=client,
        db=db,
        calendar=calendar,
        today=TODAY,
    )

    row = db.execute(
        "SELECT status, calendar_event_id FROM requests WHERE employee_id='U_SOLO'"
    ).fetchone()
    assert row["status"] == "approved"
    # notified themselves; no approval ticket routed to anyone else
    assert len(client.chat_postMessage_calls) == 1
    assert client.chat_postMessage_calls[0]["channel"] == "U_SOLO"
    assert "blocks" not in client.chat_postMessage_calls[0]
    # auto-approval created a calendar event and stored its id
    assert len(calendar.created) == 1
    assert row["calendar_event_id"] == calendar.created[0]["id"]


def test_submit_converts_buddhist_era_dates(db):
    # Thai-locale Slack date pickers send Buddhist-era years (CE + 543).
    upsert_employee(db, "U_SOLO", "Solo", None)
    calendar = FakeCalendar()
    view = make_leave_view("vacation", "2569-06-10", "2569-06-11")  # = 2026-06-10/11

    submit_leave(
        ack=FakeAck(),
        body={"user": {"id": "U_SOLO"}},
        view=view,
        client=FakeSlackClient(),
        db=db,
        calendar=calendar,
        today=TODAY,
    )

    row = db.execute(
        "SELECT start_date, end_date FROM requests WHERE employee_id='U_SOLO'"
    ).fetchone()
    assert row["start_date"] == date(2026, 6, 10)
    assert row["end_date"] == date(2026, 6, 11)
    # the calendar event uses the converted (Gregorian) date too
    assert calendar.created[0]["start"] == date(2026, 6, 10)


def test_submit_invalid_acks_errors_and_persists_nothing(db):
    upsert_employee(db, "U_BOSS", "Boss", None)
    upsert_employee(db, "U_ALICE", "Alice", "U_BOSS")
    ack = FakeAck()
    client = FakeSlackClient()
    calendar = FakeCalendar()
    view = make_leave_view("vacation", "2026-06-12", "2026-06-10")  # end before start

    submit_leave(
        ack=ack,
        body={"user": {"id": "U_ALICE"}},
        view=view,
        client=client,
        db=db,
        calendar=calendar,
        today=TODAY,
    )

    assert ack.response["response_action"] == "errors"
    assert "end_date" in ack.response["errors"]
    count = db.execute("SELECT count(*) AS n FROM requests").fetchone()["n"]
    assert count == 0
    assert client.chat_postMessage_calls == []
    assert calendar.created == []
