from datetime import date

from leave.blocks import LEAVE_CALLBACK_ID, LEAVE_TYPES
from leave.handlers import (
    CONTACT_ADMIN,
    handle_approve,
    open_leave_modal,
    resolve_approval_mode,
    submit_leave,
)
from leave.requests import approve_request, cancellable_requests, create_request, get_request
from leave.seed import upsert_employee
from tests.fakes import (
    FakeAck,
    FakeCalendar,
    FakeSlackClient,
    make_action_body,
    make_leave_view,
)

TODAY = date(2026, 6, 8)


def _block_by_id(view, block_id):
    return next(b for b in view["blocks"] if b.get("block_id") == block_id)


def _persisted(db, employee_id):
    """The request submit_leave persisted, read via the by-employee seam. Every
    request these tests create is future-dated, so it appears in the cancellable
    list; returns None when nothing was persisted."""
    rows = cancellable_requests(db, employee_id, TODAY)
    return rows[0] if rows else None


def test_resolver_uses_stored_approval():
    # A stored value wins outright, regardless of the manager relationship.
    assert resolve_approval_mode({"slack_user_id": "U_A", "manager_id": "U_B", "approval": "auto"}) == "auto"
    assert (
        resolve_approval_mode({"slack_user_id": "U_A", "manager_id": None, "approval": "approval-needed"})
        == "approval-needed"
    )


def test_resolver_derives_default_when_absent():
    # No stored approval: preserve today's _self_approves rule.
    assert resolve_approval_mode({"slack_user_id": "U_A", "manager_id": None}) == "auto"
    assert resolve_approval_mode({"slack_user_id": "U_A", "manager_id": "U_A"}) == "auto"
    assert resolve_approval_mode({"slack_user_id": "U_A", "manager_id": "U_B"}) == "approval-needed"


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
    row = _persisted(db, "U_ALICE")
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

    row = _persisted(db, "U_SOLO")
    assert row["status"] == "approved"
    # notified themselves; no approval ticket routed to anyone else
    assert len(client.chat_postMessage_calls) == 1
    assert client.chat_postMessage_calls[0]["channel"] == "U_SOLO"
    assert "blocks" not in client.chat_postMessage_calls[0]
    # auto-approval created a calendar event and stored its id
    assert len(calendar.created) == 1
    assert row["calendar_event_id"] == calendar.created[0]["id"]


def test_submit_auto_approves_when_employee_is_their_own_manager(db):
    # An admin may set someone as their own manager — there's no separate approver,
    # so it must auto-approve, not DM the person a ticket to approve themselves.
    upsert_employee(db, "U_SOLO", "Solo", "U_SOLO")  # own manager
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

    row = _persisted(db, "U_SOLO")
    assert row["status"] == "approved"
    # self-notify only — no approval ticket (blocks) routed anywhere
    assert len(client.chat_postMessage_calls) == 1
    assert client.chat_postMessage_calls[0]["channel"] == "U_SOLO"
    assert "blocks" not in client.chat_postMessage_calls[0]
    assert len(calendar.created) == 1


def test_submit_auto_mode_skips_ticket_for_distinct_manager(db):
    # approval=auto on a report with a real manager: auto-approve, no ticket.
    upsert_employee(db, "U_BOSS", "Boss", None)
    upsert_employee(db, "U_ALICE", "Alice", "U_BOSS", approval="auto")
    client = FakeSlackClient()
    calendar = FakeCalendar()
    view = make_leave_view("vacation", "2026-06-10", "2026-06-11")

    submit_leave(
        ack=FakeAck(),
        body={"user": {"id": "U_ALICE"}},
        view=view,
        client=client,
        db=db,
        calendar=calendar,
        today=TODAY,
    )

    row = _persisted(db, "U_ALICE")
    assert row["status"] == "approved"
    # self-notify only — no ticket routed to the manager
    assert len(client.chat_postMessage_calls) == 1
    assert client.chat_postMessage_calls[0]["channel"] == "U_ALICE"
    assert "blocks" not in client.chat_postMessage_calls[0]
    assert len(calendar.created) == 1


def test_submit_approval_needed_own_manager_routes_proxy_ticket(db):
    # approval=approval-needed with the employee as their own manager: a proxy ticket
    # routed to them, which they can then action themselves.
    upsert_employee(db, "U_SOLO", "Solo", "U_SOLO", approval="approval-needed")
    client = FakeSlackClient()
    calendar = FakeCalendar()
    view = make_leave_view("vacation", "2026-06-10", "2026-06-11")

    submit_leave(
        ack=FakeAck(),
        body={"user": {"id": "U_SOLO"}},
        view=view,
        client=client,
        db=db,
        calendar=calendar,
        today=TODAY,
    )

    row = _persisted(db, "U_SOLO")
    assert row["status"] == "pending"
    # ticket DM'd to themselves, with the Approve/Decline blocks
    assert len(client.chat_postMessage_calls) == 1
    assert client.chat_postMessage_calls[0]["channel"] == "U_SOLO"
    assert client.chat_postMessage_calls[0].get("blocks")
    assert calendar.created == []

    # proxy: the employee approves their own ticket (clicker == manager_id)
    handle_approve(
        ack=FakeAck(),
        body=make_action_body(row["request_id"], "U_SOLO"),
        client=client,
        db=db,
        calendar=calendar,
    )
    assert get_request(db, row["request_id"])["status"] == "approved"


def test_submit_no_manager_auto_approves_even_if_approval_needed(db):
    # No approver to route to: auto-approve regardless of the stored mode.
    upsert_employee(db, "U_SOLO", "Solo", None, approval="approval-needed")
    client = FakeSlackClient()
    calendar = FakeCalendar()
    view = make_leave_view("vacation", "2026-06-10", "2026-06-11")

    submit_leave(
        ack=FakeAck(),
        body={"user": {"id": "U_SOLO"}},
        view=view,
        client=client,
        db=db,
        calendar=calendar,
        today=TODAY,
    )

    row = _persisted(db, "U_SOLO")
    assert row["status"] == "approved"
    assert len(client.chat_postMessage_calls) == 1
    assert client.chat_postMessage_calls[0]["channel"] == "U_SOLO"
    assert "blocks" not in client.chat_postMessage_calls[0]
    assert len(calendar.created) == 1


def test_submit_single_day_defaults_end_to_start(db):
    # End date is optional; leaving it blank means a one-day leave (end = start).
    upsert_employee(db, "U_SOLO", "Solo", None)
    calendar = FakeCalendar()
    view = make_leave_view("vacation", "2026-06-10", None)  # no end date selected

    submit_leave(
        ack=FakeAck(),
        body={"user": {"id": "U_SOLO"}},
        view=view,
        client=FakeSlackClient(),
        db=db,
        calendar=calendar,
        today=TODAY,
    )

    row = _persisted(db, "U_SOLO")
    assert row["start_date"] == date(2026, 6, 10)
    assert row["end_date"] == date(2026, 6, 10)
    assert calendar.created[0]["end"] == date(2026, 6, 10)


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

    row = _persisted(db, "U_SOLO")
    assert row["start_date"] == date(2026, 6, 10)
    assert row["end_date"] == date(2026, 6, 11)
    # the calendar event uses the converted (Gregorian) date too
    assert calendar.created[0]["start"] == date(2026, 6, 10)


def _ticket_blocks(client):
    """Blocks of the approval ticket DM'd to the manager."""
    return client.chat_postMessage_calls[0].get("blocks", [])


def _coverage_text(blocks):
    """The Coverage Radar warning section text, or None if the ticket has none."""
    for b in blocks:
        if b.get("type") == "section" and "Coverage check" in b["text"]["text"]:
            return b["text"]["text"]
    return None


def _submit_alice_vacation(db, client):
    view = make_leave_view("vacation", "2026-06-10", "2026-06-11", "trip")
    submit_leave(
        ack=FakeAck(),
        body={"user": {"id": "U_ALICE"}},
        view=view,
        client=client,
        db=db,
        calendar=FakeCalendar(),
        today=TODAY,
    )


def test_ticket_warns_when_peer_leave_overlaps(db):
    upsert_employee(db, "U_BOSS", "Boss", None)
    upsert_employee(db, "U_ALICE", "Alice", "U_BOSS")
    upsert_employee(db, "U_BOB", "Bob", "U_BOSS")
    # Bob (a peer) has approved SICK leave overlapping Alice's requested dates.
    rid = create_request(db, "U_BOB", "sick", date(2026, 6, 10), date(2026, 6, 12), None)
    approve_request(db, rid)

    client = FakeSlackClient()
    _submit_alice_vacation(db, client)
    blocks = _ticket_blocks(client)
    text = _coverage_text(blocks)
    assert text is not None
    assert "Bob" in text and "approved" in text
    assert "2026-06-10" in text  # the peak overlapping day
    assert "sick" not in text  # a peer's leave type is never revealed
    # The warning is a heads-up only — the Approve/Decline buttons remain.
    assert any(b.get("block_id") == "ticket_actions" for b in blocks)


def test_ticket_has_no_warning_when_no_peer_overlaps(db):
    upsert_employee(db, "U_BOSS", "Boss", None)
    upsert_employee(db, "U_ALICE", "Alice", "U_BOSS")
    upsert_employee(db, "U_BOB", "Bob", "U_BOSS")
    # Bob is off, but well clear of Alice's dates.
    rid = create_request(db, "U_BOB", "vacation", date(2026, 6, 22), date(2026, 6, 23), None)
    approve_request(db, rid)

    client = FakeSlackClient()
    _submit_alice_vacation(db, client)
    assert _coverage_text(_ticket_blocks(client)) is None


def test_no_warning_when_requester_is_managers_only_report(db):
    upsert_employee(db, "U_BOSS", "Boss", None)
    upsert_employee(db, "U_ALICE", "Alice", "U_BOSS")  # the only report
    client = FakeSlackClient()
    _submit_alice_vacation(db, client)
    assert _coverage_text(_ticket_blocks(client)) is None


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
    assert _persisted(db, "U_ALICE") is None
    assert client.chat_postMessage_calls == []
    assert calendar.created == []
