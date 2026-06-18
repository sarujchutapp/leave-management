from datetime import date

from leave.blocks import (
    CARRY_OVER_CALLBACK_ID,
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
    open_carry_over,
    open_control_menu,
    open_leave_limits,
    open_view_settings,
    submit_carry_over,
    submit_leave_limits,
)
from leave.policy import POLICY_KEY, get_policy, set_policy
from leave.requests import recompute_all_carry_in, remaining_balance, remaining_balances
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


def _carry_over_view(max_carry_over, max_total):
    """A view_submission state payload matching build_carry_over_modal."""
    return {
        "state": {
            "values": {
                "max_carry_over": {"value": {"value": str(max_carry_over)}},
                "max_total": {"value": {"value": str(max_total)}},
            }
        }
    }


def _seed_carry_2027(db, uid):
    """Materialise an employee whose stored carry_in[2027] is 5 (no usage: leftover
    10 capped to max_carry_over 5), so a later cap change has something to lower."""
    upsert_employee(db, uid, uid, None)
    remaining_balance(db, get_employee(db, uid), "vacation", date(2026, 6, 1))
    remaining_balance(db, get_employee(db, uid), "vacation", date(2027, 6, 1))


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


# --- Carry-over modal + recompute-all (#32) ----------------------------------


def test_carry_over_modal_prefilled_with_current_caps(db):
    set_policy(db, max_carry_over={"vacation": 7}, max_total={"vacation": 18})
    client = FakeSlackClient()
    ack = FakeAck()
    open_carry_over(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}, "trigger_id": "T"},
        client=client,
        db=db,
        admin_ids=ADMINS,
    )
    assert len(client.views_push_calls) == 1
    view = client.views_push_calls[0]["view"]
    assert view["callback_id"] == CARRY_OVER_CALLBACK_ID
    assert _input_initial(view, "max_carry_over") == "7"
    assert _input_initial(view, "max_total") == "18"


def test_carry_over_submit_updates_policy_preserving_allowances(db):
    set_policy(
        db,
        allowances={"sick": 30, "vacation": 12, "personal": 7},
        max_carry_over={"vacation": 5},
        max_total={"vacation": 15},
        consecutive_limit={"vacation": 14},
    )
    ack = FakeAck()
    submit_carry_over(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_carry_over_view(8, 20),
        db=db,
        admin_ids=ADMINS,
        today=date(2027, 6, 1),
    )
    assert ack.called and ack.response is None
    p = get_policy(db)
    assert p["max_carry_over"]["vacation"] == 8
    assert p["max_total"]["vacation"] == 20
    # The other policy sections are left intact (set_policy overwrites the item).
    assert p["allowances"] == {"sick": 30, "vacation": 12, "personal": 7}
    assert p["consecutive_limit"]["vacation"] == 14


def test_carry_over_submit_recomputes_all_carry_in(db):
    set_policy(
        db,
        allowances={"sick": 30, "vacation": 10, "personal": 5},
        max_carry_over={"vacation": 5},
        max_total={"vacation": 15},
    )
    _seed_carry_2027(db, "U_A")
    _seed_carry_2027(db, "U_B")
    assert get_employee(db, "U_A")["carry_in"]["2027"] == 5
    assert get_employee(db, "U_B")["carry_in"]["2027"] == 5

    submit_carry_over(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_carry_over_view(3, 15),
        db=db,
        admin_ids=ADMINS,
        today=date(2027, 6, 1),
    )
    # Lowering max carry over rebuilds every employee's stored 2027 carry_in: 5 -> 3.
    assert get_policy(db)["max_carry_over"]["vacation"] == 3
    assert get_employee(db, "U_A")["carry_in"]["2027"] == 3
    assert get_employee(db, "U_B")["carry_in"]["2027"] == 3


def test_recompute_all_carry_in_skips_policy_item(db):
    set_policy(db)
    _seed_carry_2027(db, "U_A")
    recompute_all_carry_in(db, 2027)
    # The reserved central-policy item must not be treated as an employee.
    policy_item = db.employees.get_item(Key={"slack_user_id": POLICY_KEY}).get("Item")
    assert "carry_in" not in policy_item
    assert get_employee(db, "U_A")["carry_in"]["2027"] == 5


def test_carry_over_invalid_input_writes_nothing(db):
    set_policy(db, max_carry_over={"vacation": 5}, max_total={"vacation": 15})
    ack = FakeAck()
    submit_carry_over(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_carry_over_view("x", -1),
        db=db,
        admin_ids=ADMINS,
        today=date(2027, 6, 1),
    )
    assert ack.response["response_action"] == "errors"
    assert set(ack.response["errors"]) == {"max_carry_over", "max_total"}
    assert get_policy(db)["max_carry_over"]["vacation"] == 5


def test_carry_over_non_admin_submit_rejected(db):
    set_policy(db, max_carry_over={"vacation": 5}, max_total={"vacation": 15})
    ack = FakeAck()
    submit_carry_over(
        ack=ack,
        body={"user": {"id": "U_OTHER"}},
        view=_carry_over_view(1, 1),
        db=db,
        admin_ids=ADMINS,
        today=date(2027, 6, 1),
    )
    assert ack.called
    assert get_policy(db)["max_carry_over"]["vacation"] == 5
