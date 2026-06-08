import logging

from leave.blocks import LEAVE_CALLBACK_ID, LEAVE_TYPES
from leave.handlers import CONTACT_ADMIN, open_leave_modal, submit_leave
from leave.seed import upsert_employee
from tests.fakes import FakeAck, FakeSlackClient


def test_registered_user_opens_modal(conn):
    upsert_employee(conn, "U_ALICE", "Alice", None)
    client = FakeSlackClient()
    ack = FakeAck()

    open_leave_modal(
        ack=ack, body={"user_id": "U_ALICE", "trigger_id": "T123"}, client=client, conn=conn
    )

    assert ack.called
    assert ack.response is None  # acked empty, not with a message
    assert len(client.views_open_calls) == 1

    view = client.views_open_calls[0]["view"]
    assert view["callback_id"] == LEAVE_CALLBACK_ID
    block_ids = [b["block_id"] for b in view["blocks"] if "block_id" in b]
    assert block_ids == ["leave_type", "start_date", "end_date", "reason"]
    type_options = [o["value"] for o in view["blocks"][0]["element"]["options"]]
    assert type_options == LEAVE_TYPES


def test_unregistered_user_gets_contact_admin(conn):
    client = FakeSlackClient()
    ack = FakeAck()

    open_leave_modal(
        ack=ack, body={"user_id": "U_NOPE", "trigger_id": "T"}, client=client, conn=conn
    )

    assert ack.called
    assert ack.response == CONTACT_ADMIN
    assert client.views_open_calls == []


def test_submit_acknowledges():
    ack = FakeAck()
    submit_leave(ack=ack, view={"state": {"values": {}}}, logger=logging.getLogger("test"))
    assert ack.called
