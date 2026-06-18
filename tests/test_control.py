from leave.blocks import (
    CONTROL_MENU_CALLBACK_ID,
    LEAVE_LIMITS_ACTION,
    REPORT_ACTION,
    SETTINGS_VIEW_CALLBACK_ID,
    VIEW_SETTINGS_ACTION,
)
from leave.handlers import NOT_ADMIN, is_admin, open_control_menu, open_view_settings
from leave.policy import set_policy
from tests.fakes import FakeAck, FakeSlackClient

ADMINS = {"U_ADMIN"}


def _menu_action_ids(view):
    actions = next(b for b in view["blocks"] if b["type"] == "actions")
    return {e["action_id"] for e in actions["elements"]}


def test_is_admin_recognises_allowlist_members():
    assert is_admin("U_ADMIN", ADMINS) is True
    assert is_admin("U_OTHER", ADMINS) is False
    # An empty allowlist admits no one (the safe default when unset).
    assert is_admin("U_ADMIN", set()) is False


def test_non_admin_control_gets_no_menu():
    client = FakeSlackClient()
    ack = FakeAck()
    open_control_menu(
        ack=ack,
        body={"user_id": "U_OTHER", "trigger_id": "T"},
        client=client,
        admin_ids=ADMINS,
    )
    assert ack.response == NOT_ADMIN
    assert client.views_open_calls == []


def test_admin_control_opens_menu_listing_actions():
    client = FakeSlackClient()
    ack = FakeAck()
    open_control_menu(
        ack=ack,
        body={"user_id": "U_ADMIN", "trigger_id": "T123"},
        client=client,
        admin_ids=ADMINS,
    )
    assert ack.called and ack.response is None
    assert len(client.views_open_calls) == 1
    view = client.views_open_calls[0]["view"]
    assert view["callback_id"] == CONTROL_MENU_CALLBACK_ID
    # The menu routes to View Settings (built) and names the other admin actions.
    action_ids = _menu_action_ids(view)
    assert VIEW_SETTINGS_ACTION in action_ids
    assert LEAVE_LIMITS_ACTION in action_ids
    assert REPORT_ACTION in action_ids


def test_view_settings_renders_current_policy(db):
    set_policy(
        db,
        allowances={"sick": 30, "vacation": 12, "personal": 5},
        max_carry_over={"vacation": 6},
        max_total={"vacation": 16},
        consecutive_limit={"vacation": 14},
    )
    client = FakeSlackClient()
    ack = FakeAck()
    open_view_settings(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}, "trigger_id": "T"},
        client=client,
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.called
    assert len(client.views_push_calls) == 1
    view = client.views_push_calls[0]["view"]
    assert view["callback_id"] == SETTINGS_VIEW_CALLBACK_ID
    text = " ".join(
        b["text"]["text"] for b in view["blocks"] if b["type"] == "section"
    )
    # Every policy figure the admin needs is shown read-only.
    assert "12" in text and "5" in text and "30" in text  # allowances
    assert "6" in text  # max carry over
    assert "16" in text  # max total
    assert "14" in text  # consecutive limit


def test_view_settings_rejects_non_admin(db):
    set_policy(db)
    client = FakeSlackClient()
    ack = FakeAck()
    open_view_settings(
        ack=ack,
        body={"user": {"id": "U_OTHER"}, "trigger_id": "T"},
        client=client,
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.called
    assert client.views_push_calls == []
