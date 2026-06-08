import logging

from leave.blocks import LEAVE_CALLBACK_ID, LEAVE_TYPES
from leave.handlers import open_leave_modal, submit_leave
from tests.fakes import FakeAck, FakeSlackClient


def test_leave_command_opens_modal():
    client = FakeSlackClient()
    ack = FakeAck()

    open_leave_modal(ack=ack, body={"trigger_id": "T123"}, client=client)

    assert ack.called
    assert len(client.views_open_calls) == 1
    call = client.views_open_calls[0]
    assert call["trigger_id"] == "T123"

    view = call["view"]
    assert view["callback_id"] == LEAVE_CALLBACK_ID
    block_ids = [b["block_id"] for b in view["blocks"] if "block_id" in b]
    assert block_ids == ["leave_type", "start_date", "end_date", "reason"]

    type_options = [o["value"] for o in view["blocks"][0]["element"]["options"]]
    assert type_options == LEAVE_TYPES


def test_submit_acknowledges():
    ack = FakeAck()
    view = {"state": {"values": {}}}

    submit_leave(ack=ack, view=view, logger=logging.getLogger("test"))

    assert ack.called
