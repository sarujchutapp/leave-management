"""Test doubles for Slack client and ack, recording calls for assertions."""


class FakeCalendar:
    def __init__(self):
        self.created = []
        self.deleted = []

    def create_event(self, summary, start, end):
        event_id = f"evt{len(self.created) + 1}"
        self.created.append({"summary": summary, "start": start, "end": end, "id": event_id})
        return event_id

    def delete_event(self, event_id):
        self.deleted.append(event_id)


def make_action_body(value, user_id, channel="C1", ts="111.1", trigger_id="T"):
    """A block_actions payload (Approve/Decline button click)."""
    return {
        "actions": [{"value": str(value)}],
        "user": {"id": user_id},
        "channel": {"id": channel},
        "message": {"ts": ts},
        "trigger_id": trigger_id,
    }


def make_cancel_view(request_id):
    return {
        "state": {
            "values": {"request": {"value": {"selected_option": {"value": str(request_id)}}}}
        }
    }


def make_decline_view(private_metadata, reason=None):
    return {
        "private_metadata": private_metadata,
        "state": {"values": {"decline_reason": {"value": {"value": reason}}}},
    }


def make_leave_view(leave_type, start, end, reason=None):
    """Build a view_submission state payload matching build_leave_modal."""
    return {
        "state": {
            "values": {
                "leave_type": {"value": {"selected_option": {"value": leave_type}}},
                "start_date": {"value": {"selected_date": start}},
                "end_date": {"value": {"selected_date": end}},
                "reason": {"value": {"value": reason}},
            }
        }
    }


class FakeAck:
    def __init__(self):
        self.called = False
        self.response = None

    def __call__(self, *args, **kwargs):
        self.called = True
        # ack() for view submissions may carry a response_action payload
        if args:
            self.response = args[0]
        elif kwargs:
            self.response = kwargs


class FakeSlackClient:
    def __init__(self):
        self.views_open_calls = []
        self.chat_postMessage_calls = []
        self.views_update_calls = []
        self.chat_update_calls = []

    def views_open(self, **kwargs):
        self.views_open_calls.append(kwargs)
        return {"ok": True}

    def chat_postMessage(self, **kwargs):
        self.chat_postMessage_calls.append(kwargs)
        return {"ok": True, "ts": "1.0", "channel": kwargs.get("channel")}

    def chat_update(self, **kwargs):
        self.chat_update_calls.append(kwargs)
        return {"ok": True}

    def views_update(self, **kwargs):
        self.views_update_calls.append(kwargs)
        return {"ok": True}
