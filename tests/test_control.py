from datetime import date

from leave.blocks import (
    CONTROL_MENU_CALLBACK_ID,
    LEAVE_LIMITS_ACTION,
    LEAVE_LIMITS_CALLBACK_ID,
    REPORT_ACTION,
    SETTINGS_VIEW_CALLBACK_ID,
    VIEW_SETTINGS_ACTION,
)
from leave.db import get_employee
from leave.handlers import (
    NOT_ADMIN,
    is_admin,
    open_control_menu,
    open_leave_limits,
    open_view_settings,
    submit_leave_limits,
)
from leave.policy import get_policy, set_policy
from leave.requests import remaining_balances
from leave.seed import upsert_employee
from tests.fakes import FakeAck, FakeSlackClient

ADMINS = {"U_ADMIN"}
TODAY = date(2026, 6, 8)


def _input_initial(view, block_id):
    block = next(b for b in view["blocks"] if b.get("block_id") == block_id)
    return block["element"].get("initial_value")


def _leave_limits_view(sick, vacation, personal, consecutive):
    """A view_submission state payload matching build_leave_limits_modal."""
    return {
        "state": {
            "values": {
                "sick": {"value": {"value": str(sick)}},
                "vacation": {"value": {"value": str(vacation)}},
                "personal": {"value": {"value": str(personal)}},
                "consecutive_limit": {"value": {"value": str(consecutive)}},
            }
        }
    }


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


# --- Leave limits modal (#31) ------------------------------------------------


def test_leave_limits_modal_prefilled_with_current_policy(db):
    set_policy(
        db,
        allowances={"sick": 30, "vacation": 12, "personal": 5},
        consecutive_limit={"vacation": 14},
    )
    client = FakeSlackClient()
    ack = FakeAck()
    open_leave_limits(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}, "trigger_id": "T"},
        client=client,
        db=db,
        admin_ids=ADMINS,
    )
    assert len(client.views_push_calls) == 1
    view = client.views_push_calls[0]["view"]
    assert view["callback_id"] == LEAVE_LIMITS_CALLBACK_ID
    assert _input_initial(view, "sick") == "30"
    assert _input_initial(view, "vacation") == "12"
    assert _input_initial(view, "personal") == "5"
    assert _input_initial(view, "consecutive_limit") == "14"


def test_leave_limits_submit_updates_policy(db):
    set_policy(db, allowances={"sick": 30, "vacation": 10, "personal": 5})
    ack = FakeAck()
    submit_leave_limits(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_leave_limits_view(28, 15, 7, 20),
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.called and ack.response is None
    p = get_policy(db)
    assert p["allowances"] == {"sick": 28, "vacation": 15, "personal": 7}
    assert p["consecutive_limit"]["vacation"] == 20


def test_leave_limits_change_flows_live_into_balances(db):
    upsert_employee(db, "U_E", "Eve", None)
    set_policy(db, allowances={"sick": 30, "vacation": 10, "personal": 5})
    submit_leave_limits(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_leave_limits_view(30, 18, 5, 15),
        db=db,
        admin_ids=ADMINS,
    )
    emp = get_employee(db, "U_E")
    # No stored-state migration: the new vacation allowance is reflected on read.
    assert remaining_balances(db, emp, TODAY)["vacation"] == 18


def test_leave_limits_preserves_carry_over_caps(db):
    set_policy(
        db,
        allowances={"sick": 30, "vacation": 10, "personal": 5},
        max_carry_over={"vacation": 6},
        max_total={"vacation": 16},
    )
    submit_leave_limits(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_leave_limits_view(30, 11, 5, 15),
        db=db,
        admin_ids=ADMINS,
    )
    p = get_policy(db)
    # Editing allowances must not silently reset the carry-over caps to defaults.
    assert p["max_carry_over"]["vacation"] == 6
    assert p["max_total"]["vacation"] == 16


def test_leave_limits_invalid_input_writes_nothing(db):
    set_policy(db, allowances={"sick": 30, "vacation": 10, "personal": 5})
    ack = FakeAck()
    submit_leave_limits(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_leave_limits_view("abc", -3, 5, 15),
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.response["response_action"] == "errors"
    assert set(ack.response["errors"]) == {"sick", "vacation"}
    # Nothing written: policy unchanged.
    assert get_policy(db)["allowances"] == {"sick": 30, "vacation": 10, "personal": 5}


def test_leave_limits_non_admin_submit_rejected(db):
    set_policy(db, allowances={"sick": 30, "vacation": 10, "personal": 5})
    ack = FakeAck()
    submit_leave_limits(
        ack=ack,
        body={"user": {"id": "U_OTHER"}},
        view=_leave_limits_view(1, 1, 1, 1),
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.called
    assert get_policy(db)["allowances"] == {"sick": 30, "vacation": 10, "personal": 5}
