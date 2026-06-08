"""Test doubles for Slack client and ack, recording calls for assertions."""


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

    def views_open(self, **kwargs):
        self.views_open_calls.append(kwargs)
        return {"ok": True}

    def chat_postMessage(self, **kwargs):
        self.chat_postMessage_calls.append(kwargs)
        return {"ok": True, "ts": "1.0", "channel": kwargs.get("channel")}

    def views_update(self, **kwargs):
        self.views_update_calls.append(kwargs)
        return {"ok": True}
