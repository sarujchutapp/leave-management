import csv
import io
from datetime import date

from leave.blocks import (
    CARRY_OVER_CALLBACK_ID,
    CARRY_OVER_TOGGLE_ACTION,
    CLEAR_CALLBACK_ID,
    CONTROL_MENU_CALLBACK_ID,
    HOLIDAYS_CALLBACK_ID,
    CONSECUTIVE_TOGGLE_ACTION,
    LEAVE_LIMITS_ACTION,
    LEAVE_LIMITS_CALLBACK_ID,
    MANAGE_ACTION_SELECT,
    MANAGE_EMPLOYEES_CALLBACK_ID,
    REPORT_ACTION,
    REPORT_CALLBACK_ID,
    REPORT_TYPE_ACTION,
    SETTINGS_VIEW_CALLBACK_ID,
    VIEW_SETTINGS_ACTION,
)
from leave.board import BOARD_KEY, get_board
from leave.db import get_employee
from leave.handlers import (
    NOT_ADMIN,
    is_admin,
    open_carry_over,
    open_clear,
    open_control_menu,
    open_holidays,
    open_leave_limits,
    open_manage_employees,
    open_report,
    open_view_settings,
    update_carry_over_modal,
    update_leave_limits_modal,
    submit_carry_over,
    submit_clear,
    submit_holidays,
    submit_leave_limits,
    submit_manage_employees,
    submit_report,
    update_manage_modal,
    update_report_modal,
)
from leave.holidays import get_holiday, holidays_for_year, upsert_holiday
from leave.report import build_burnout_csv, build_history_csv, build_report_csv
from leave.policy import POLICY_KEY, get_policy, set_policy
from leave.requests import (
    approve_request,
    clear_all_requests,
    create_request,
    get_request,
    recompute_all_carry_in,
    remaining_balance,
    remaining_balances,
    set_calendar_event_id,
    set_ticket_ref,
)
from leave.seed import upsert_employee
from tests.fakes import FakeAck, FakeCalendar, FakeSheets, FakeSlackClient

ADMINS = {"U_ADMIN"}
TODAY = date(2026, 6, 8)


def _input_initial(view, block_id):
    block = next(b for b in view["blocks"] if b.get("block_id") == block_id)
    return block["element"].get("initial_value")


def _leave_limits_view(sick, vacation, personal, consecutive, enforce_consecutive=True):
    """A view_submission state payload matching build_leave_limits_modal."""
    return {
        "state": {
            "values": {
                "sick": {"value": {"value": str(sick)}},
                "vacation": {"value": {"value": str(vacation)}},
                "personal": {"value": {"value": str(personal)}},
                "consecutive_limit": {"value": {"value": str(consecutive)}},
                "enforce_consecutive": {
                    CONSECUTIVE_TOGGLE_ACTION: {
                        "selected_options": [{"value": "on"}] if enforce_consecutive else []
                    }
                },
            }
        }
    }


def _carry_over_view(max_carry_over, max_total, enable=True):
    """A view_submission state payload matching build_carry_over_modal."""
    return {
        "state": {
            "values": {
                "max_carry_over": {"value": {"value": str(max_carry_over)}},
                "max_total": {"value": {"value": str(max_total)}},
                "enable_carry_over": {
                    CARRY_OVER_TOGGLE_ACTION: {
                        "selected_options": [{"value": "on"}] if enable else []
                    }
                },
            }
        }
    }


def _seed_carry_2027(db, uid):
    """Materialise an employee whose stored carry_in[2027] is 5 (no usage: leftover
    10 capped to max_carry_over 5), so a later cap change has something to lower."""
    upsert_employee(db, uid, uid, None)
    remaining_balance(db, get_employee(db, uid), "vacation", date(2026, 6, 1))
    remaining_balance(db, get_employee(db, uid), "vacation", date(2027, 6, 1))


def _clear_view(word):
    """A view_submission state payload matching build_clear_modal."""
    return {"state": {"values": {"confirm": {"value": {"value": word}}}}}


def _seed_approved_with_event(db, emp_id, event_id):
    rid = create_request(db, emp_id, "vacation", date(2026, 6, 8), date(2026, 6, 9), None)
    approve_request(db, rid)
    set_calendar_event_id(db, rid, event_id)
    return rid


def _manage_view(employee, action="save", name=None, manager=None, overrides=None):
    """A view_submission state payload matching build_manage_employees_modal."""
    overrides = overrides or {}
    values = {
        "employee": {"value": {"selected_user": employee}},
        "action": {MANAGE_ACTION_SELECT: {"selected_option": {"value": action}}},
        "name": {"value": {"value": name}},
        "manager": {"value": {"selected_user": manager}},
    }
    for t in ("sick", "vacation", "personal"):
        values[f"override_{t}"] = {
            "value": {"value": str(overrides[t]) if t in overrides else None}
        }
    return {"state": {"values": values}}


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


def test_view_settings_shows_disabled_caps(db):
    set_policy(
        db,
        allowances={"sick": 30, "vacation": 12, "personal": 5},
        max_carry_over={"vacation": 0},
        max_total={"vacation": 16},
        consecutive_limit={"vacation": None},
    )
    client = FakeSlackClient()
    open_view_settings(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}, "trigger_id": "T"},
        client=client,
        db=db,
        admin_ids=ADMINS,
    )
    text = " ".join(
        b["text"]["text"] for b in client.views_push_calls[0]["view"]["blocks"] if b["type"] == "section"
    )
    assert "No limit" in text  # consecutive limit off
    assert "disabled" in text.lower()  # carry-over off


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


def test_leave_limits_modal_hides_consecutive_when_disabled(db):
    # With the cap off (None), the modal opens with the checkbox unchecked and the
    # number field hidden (render-from-state).
    set_policy(
        db,
        allowances={"sick": 30, "vacation": 10, "personal": 5},
        consecutive_limit={"vacation": None},
    )
    client = FakeSlackClient()
    open_leave_limits(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}, "trigger_id": "T"},
        client=client,
        db=db,
        admin_ids=ADMINS,
    )
    view = client.views_push_calls[0]["view"]
    ids = {b.get("block_id") for b in view["blocks"]}
    assert "enforce_consecutive" in ids  # checkbox present
    assert "consecutive_limit" not in ids  # number hidden when off
    checkbox = next(b for b in view["blocks"] if b.get("block_id") == "enforce_consecutive")
    assert "initial_options" not in checkbox["element"]  # unchecked


def test_leave_limits_toggle_consecutive_rerenders(db):
    # Toggling the checkbox re-renders in place: enabling shows the number field,
    # disabling hides it.
    set_policy(
        db,
        allowances={"sick": 30, "vacation": 10, "personal": 5},
        consecutive_limit={"vacation": None},
    )
    client = FakeSlackClient()
    update_leave_limits_modal(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}, "view": {"id": "V1"},
              "actions": [{"selected_options": [{"value": "on"}]}]},
        client=client,
        db=db,
        admin_ids=ADMINS,
    )
    assert client.views_update_calls[0]["view_id"] == "V1"
    assert "consecutive_limit" in {
        b.get("block_id") for b in client.views_update_calls[0]["view"]["blocks"]
    }
    update_leave_limits_modal(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}, "view": {"id": "V1"},
              "actions": [{"selected_options": []}]},
        client=client,
        db=db,
        admin_ids=ADMINS,
    )
    assert "consecutive_limit" not in {
        b.get("block_id") for b in client.views_update_calls[1]["view"]["blocks"]
    }


def test_leave_limits_submit_updates_policy(db):
    set_policy(db, allowances={"sick": 30, "vacation": 10, "personal": 5})
    client = FakeSlackClient()
    ack = FakeAck()
    submit_leave_limits(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_leave_limits_view(28, 15, 7, 20),
        client=client,
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.response == {"response_action": "clear"}  # modal closes on success
    assert len(client.chat_postMessage_calls) == 1  # admin gets a confirmation DM
    p = get_policy(db)
    assert p["allowances"] == {"sick": 28, "vacation": 15, "personal": 7}
    assert p["consecutive_limit"]["vacation"] == 20


def test_leave_limits_change_flows_live_into_balances(db):
    upsert_employee(db, "U_E", "Eve", None)
    # Max total >= the new allowance so the invariant is satisfied.
    set_policy(db, allowances={"sick": 30, "vacation": 10, "personal": 5}, max_total={"vacation": 20})
    submit_leave_limits(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_leave_limits_view(30, 18, 5, 15),
        client=FakeSlackClient(),
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
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
    )
    p = get_policy(db)
    # Editing allowances must not silently reset the carry-over caps to defaults.
    assert p["max_carry_over"]["vacation"] == 6
    assert p["max_total"]["vacation"] == 16


def test_leave_limits_disable_consecutive_stores_none(db):
    # Unchecking "Enforce consecutive limit" stores None (no cap), ignoring the number.
    set_policy(db, allowances={"sick": 30, "vacation": 10, "personal": 5}, consecutive_limit={"vacation": 15})
    submit_leave_limits(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_leave_limits_view(30, 10, 5, 15, enforce_consecutive=False),
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
    )
    assert get_policy(db)["consecutive_limit"]["vacation"] is None


def test_leave_limits_invalid_input_writes_nothing(db):
    set_policy(db, allowances={"sick": 30, "vacation": 10, "personal": 5})
    ack = FakeAck()
    submit_leave_limits(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_leave_limits_view("abc", -3, 5, 15),
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.response["response_action"] == "errors"
    assert set(ack.response["errors"]) == {"sick", "vacation"}
    # Nothing written: policy unchanged.
    assert get_policy(db)["allowances"] == {"sick": 30, "vacation": 10, "personal": 5}


def test_leave_limits_vacation_allowance_capped_by_max_total(db):
    # A vacation allowance above the stored Max total would silently cap everyone below
    # it — block it (the cross-modal invariant from grilling #2).
    set_policy(db, allowances={"sick": 30, "vacation": 10, "personal": 5}, max_total={"vacation": 15})
    ack = FakeAck()
    submit_leave_limits(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_leave_limits_view(30, 20, 5, 15),  # vacation 20 > max total 15
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.response["response_action"] == "errors"
    assert "vacation" in ack.response["errors"]
    assert get_policy(db)["allowances"]["vacation"] == 10  # nothing written


def test_leave_limits_non_admin_submit_rejected(db):
    set_policy(db, allowances={"sick": 30, "vacation": 10, "personal": 5})
    ack = FakeAck()
    submit_leave_limits(
        ack=ack,
        body={"user": {"id": "U_OTHER"}},
        view=_leave_limits_view(1, 1, 1, 1),
        client=FakeSlackClient(),
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


def test_carry_over_modal_hides_field_when_disabled(db):
    # max_carry_over 0 = carry-over off: checkbox unchecked, max carry over field
    # hidden, max total still shown.
    set_policy(
        db,
        allowances={"sick": 30, "vacation": 10, "personal": 5},
        max_carry_over={"vacation": 0},
        max_total={"vacation": 15},
    )
    client = FakeSlackClient()
    open_carry_over(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}, "trigger_id": "T"},
        client=client,
        db=db,
        admin_ids=ADMINS,
    )
    ids = {b.get("block_id") for b in client.views_push_calls[0]["view"]["blocks"]}
    assert "enable_carry_over" in ids
    assert "max_carry_over" not in ids  # hidden when disabled
    assert "max_total" in ids  # always shown


def test_carry_over_toggle_rerenders(db):
    set_policy(
        db,
        allowances={"sick": 30, "vacation": 10, "personal": 5},
        max_carry_over={"vacation": 0},
        max_total={"vacation": 15},
    )
    client = FakeSlackClient()
    update_carry_over_modal(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}, "view": {"id": "V1"},
              "actions": [{"selected_options": [{"value": "on"}]}]},
        client=client,
        db=db,
        admin_ids=ADMINS,
    )
    assert "max_carry_over" in {
        b.get("block_id") for b in client.views_update_calls[0]["view"]["blocks"]
    }


def test_carry_over_submit_updates_policy_preserving_allowances(db):
    set_policy(
        db,
        allowances={"sick": 30, "vacation": 12, "personal": 7},
        max_carry_over={"vacation": 5},
        max_total={"vacation": 15},
        consecutive_limit={"vacation": 14},
    )
    client = FakeSlackClient()
    ack = FakeAck()
    submit_carry_over(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_carry_over_view(8, 20),
        client=client,
        db=db,
        admin_ids=ADMINS,
        today=date(2027, 6, 1),
    )
    assert ack.response == {"response_action": "clear"}  # modal closes on success
    assert len(client.chat_postMessage_calls) == 1  # admin gets a confirmation DM
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
        client=FakeSlackClient(),
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


def test_carry_over_disable_stores_zero(db):
    # Unchecking "Enable carry-over" stores max_carry_over 0 (nothing rolls over).
    set_policy(db, allowances={"sick": 30, "vacation": 10, "personal": 5}, max_carry_over={"vacation": 5}, max_total={"vacation": 15})
    submit_carry_over(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_carry_over_view(5, 15, enable=False),
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
        today=date(2027, 6, 1),
    )
    assert get_policy(db)["max_carry_over"]["vacation"] == 0


def test_carry_over_max_total_below_allowance_blocked(db):
    set_policy(db, allowances={"sick": 30, "vacation": 12, "personal": 5}, max_total={"vacation": 15})
    ack = FakeAck()
    submit_carry_over(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_carry_over_view(5, 10),  # max total 10 < vacation allowance 12
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
        today=date(2027, 6, 1),
    )
    assert ack.response["response_action"] == "errors"
    assert "max_total" in ack.response["errors"]
    assert get_policy(db)["max_total"]["vacation"] == 15  # unchanged


def test_carry_over_exceeding_max_total_blocked(db):
    set_policy(db, allowances={"sick": 30, "vacation": 10, "personal": 5}, max_carry_over={"vacation": 5}, max_total={"vacation": 15})
    ack = FakeAck()
    submit_carry_over(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_carry_over_view(20, 15),  # max carry over 20 > max total 15
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
        today=date(2027, 6, 1),
    )
    assert ack.response["response_action"] == "errors"
    assert "max_carry_over" in ack.response["errors"]


def test_carry_over_invalid_input_writes_nothing(db):
    set_policy(db, max_carry_over={"vacation": 5}, max_total={"vacation": 15})
    ack = FakeAck()
    submit_carry_over(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_carry_over_view("x", -1),
        client=FakeSlackClient(),
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
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
        today=date(2027, 6, 1),
    )
    assert ack.called
    assert get_policy(db)["max_carry_over"]["vacation"] == 5


# --- Clear: typed-confirm wipe (#33) -----------------------------------------


def test_clear_modal_opens_for_admin(db):
    client = FakeSlackClient()
    ack = FakeAck()
    open_clear(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}, "trigger_id": "T"},
        client=client,
        admin_ids=ADMINS,
    )
    assert len(client.views_push_calls) == 1
    view = client.views_push_calls[0]["view"]
    assert view["callback_id"] == CLEAR_CALLBACK_ID
    assert any(b.get("block_id") == "confirm" for b in view["blocks"])


def test_clear_wrong_word_is_noop(db):
    upsert_employee(db, "U_A", "A", None)
    rid = _seed_approved_with_event(db, "U_A", "evt1")
    cal, sheets, ack = FakeCalendar(), FakeSheets(), FakeAck()
    submit_clear(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_clear_view("nope"),
        db=db,
        calendar=cal,
        sheets=sheets,
        client=FakeSlackClient(),
        admin_ids=ADMINS,
        today=TODAY,
    )
    assert ack.response["response_action"] == "errors"
    assert "confirm" in ack.response["errors"]
    assert get_request(db, rid) is not None
    assert cal.deleted == []


def test_clear_correct_word_wipes_and_preserves_the_rest(db):
    set_policy(db)
    upsert_employee(db, "U_A", "A", None)
    upsert_holiday(db, date(2026, 1, 1), "New Year")
    r1 = _seed_approved_with_event(db, "U_A", "evt1")
    r2 = _seed_approved_with_event(db, "U_A", "evt2")
    # A board item to prove it gets reset.
    db.employees.update_item(
        Key={"slack_user_id": BOARD_KEY},
        UpdateExpression="SET entries = :e",
        ExpressionAttributeValues={":e": {}},
    )
    cal, sheets, client, ack = FakeCalendar(), FakeSheets(), FakeSlackClient(), FakeAck()
    submit_clear(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_clear_view("CLEAR"),
        db=db,
        calendar=cal,
        sheets=sheets,
        client=client,
        admin_ids=ADMINS,
        today=TODAY,
    )
    assert ack.response == {"response_action": "clear"}  # modal closes on success
    assert len(client.chat_postMessage_calls) == 1  # admin gets a confirmation DM
    # Requests gone, their calendar events deleted, board reset.
    assert get_request(db, r1) is None and get_request(db, r2) is None
    assert set(cal.deleted) == {"evt1", "evt2"}
    assert get_board(db) is None
    # Employees, central policy, and holidays kept.
    assert get_employee(db, "U_A") is not None
    assert get_policy(db)["allowances"]["vacation"] == 10
    assert date(2026, 1, 1) in holidays_for_year(db, 2026)


def test_clear_wipes_carry_in(db):
    # Clear is a true clean slate (ADR-0009): stored carry-in is wiped too, so
    # everyone resets to base allowance.
    set_policy(db)
    _seed_carry_2027(db, "U_A")
    assert "carry_in" in get_employee(db, "U_A")
    clear_all_requests(db, FakeCalendar(), FakeSheets(), TODAY)
    assert "carry_in" not in get_employee(db, "U_A")


def test_clear_withdraws_pending_tickets(db):
    # Clear deletes pending rows; it also switches off the manager's still-open
    # ticket so no orphan Approve/Decline buttons remain.
    upsert_employee(db, "U_A", "A", "U_M")
    rid = create_request(db, "U_A", "vacation", date(2026, 7, 1), date(2026, 7, 2), None)
    set_ticket_ref(db, rid, "C_MGR", "999.9")
    client = FakeSlackClient()
    clear_all_requests(db, FakeCalendar(), FakeSheets(), TODAY, client=client)
    assert any(
        c["channel"] == "C_MGR" and c["ts"] == "999.9" for c in client.chat_update_calls
    )


def test_clear_non_admin_is_rejected(db):
    upsert_employee(db, "U_A", "A", None)
    rid = _seed_approved_with_event(db, "U_A", "evt1")
    cal, sheets, ack = FakeCalendar(), FakeSheets(), FakeAck()
    submit_clear(
        ack=ack,
        body={"user": {"id": "U_OTHER"}},
        view=_clear_view("CLEAR"),
        db=db,
        calendar=cal,
        sheets=sheets,
        client=FakeSlackClient(),
        admin_ids=ADMINS,
        today=TODAY,
    )
    assert ack.called
    assert get_request(db, rid) is not None
    assert cal.deleted == []


def test_clear_wipes_db_before_touching_calendar(db):
    # A slow/failing calendar must never strand the DB wipe (the Lambda-timeout
    # failure mode), so the rows must be gone before any calendar call happens.
    set_policy(db)
    upsert_employee(db, "U_A", "Alice", None)
    r1 = _seed_approved_with_event(db, "U_A", "evt1")
    r2 = _seed_approved_with_event(db, "U_A", "evt2")

    rows_remaining_when_calendar_called = []

    class OrderProbeCalendar:
        def delete_event(self, event_id):
            rows_remaining_when_calendar_called.append(len(db.requests.scan()["Items"]))

    clear_all_requests(db, OrderProbeCalendar(), FakeSheets(), TODAY)

    # Every calendar call saw an already-empty requests table.
    assert rows_remaining_when_calendar_called == [0, 0]
    assert get_request(db, r1) is None and get_request(db, r2) is None
    assert get_board(db) is None


def test_clear_requests_script_delegates_to_shared_function():
    import clear_requests
    from leave.requests import clear_all_requests

    # The script wipes via the same extracted function the handler uses.
    assert clear_requests.clear_all_requests is clear_all_requests


# --- Report: all-employee CSV (#34) ------------------------------------------


def _csv_rows(text):
    return list(csv.reader(io.StringIO(text)))


def test_report_csv_row_per_employee_and_type_with_derived_figures(db):
    set_policy(db, allowances={"sick": 30, "vacation": 10, "personal": 5})
    upsert_employee(db, "U_A", "Alice", None)
    rid = create_request(db, "U_A", "vacation", date(2026, 6, 8), date(2026, 6, 11), None)  # 4 wd
    approve_request(db, rid)

    rows = _csv_rows(build_report_csv(db, TODAY))  # TODAY = 2026-06-08
    assert rows[0] == ["employee", "leave type", "used", "remaining", "carry-in"]
    by_type = {r[1]: r for r in rows[1:]}
    # Figures match the derived balances: vacation used 4, remaining 10-4=6, carry 0.
    assert by_type["vacation"][2:] == ["4", "6", "0"]
    assert by_type["sick"][2:] == ["0", "30", "0"]
    assert by_type["personal"][2:] == ["0", "5", "0"]


def test_report_csv_skips_reserved_items(db):
    set_policy(db)
    upsert_employee(db, "U_A", "Alice", None)
    db.employees.update_item(
        Key={"slack_user_id": BOARD_KEY},
        UpdateExpression="SET entries = :e",
        ExpressionAttributeValues={":e": {}},
    )
    names = {r[0] for r in _csv_rows(build_report_csv(db, TODAY))}
    assert POLICY_KEY not in names and BOARD_KEY not in names
    assert "Alice" in names


def test_history_csv_lists_a_persons_requests_oldest_first(db):
    set_policy(db)
    upsert_employee(db, "U_A", "Alice", None)
    r1 = create_request(db, "U_A", "vacation", date(2026, 6, 10), date(2026, 6, 11), "trip")  # 2 wd
    approve_request(db, r1)
    create_request(db, "U_A", "sick", date(2026, 5, 4), date(2026, 5, 4), None)  # pending, earlier

    rows = _csv_rows(build_history_csv(db, "U_A"))
    assert rows[0] == [
        "employee", "leave type", "start", "end", "half", "status",
        "working days", "reason", "decline reason",
    ]
    # Oldest first: the May sick (pending) row precedes the June vacation row.
    assert rows[1][1:6] == ["sick", "2026-05-04", "2026-05-04", "", "pending"]
    assert rows[2][1:7] == ["vacation", "2026-06-10", "2026-06-11", "", "approved", "2"]
    assert rows[2][7] == "trip"  # reason carried through


def _approved_past_leave(db, emp_id, start, end):
    """An approved leave that has already ended (a 'taken' break)."""
    rid = create_request(db, emp_id, "vacation", start, end, None)
    approve_request(db, rid)
    return rid


def test_burnout_csv_ranks_by_no_break_stretch_longest_first(db):
    set_policy(db)
    upsert_employee(db, "U_A", "Alice", None)
    upsert_employee(db, "U_B", "Bob", None)
    # Alice last broke in February and has nothing booked — a long dry spell.
    _approved_past_leave(db, "U_A", date(2026, 2, 2), date(2026, 2, 2))
    # Bob broke late May — a short stretch.
    _approved_past_leave(db, "U_B", date(2026, 5, 29), date(2026, 5, 29))

    rows = _csv_rows(build_burnout_csv(db, TODAY))  # TODAY = 2026-06-08
    assert rows[0] == [
        "employee", "no-break stretch (days)", "remaining vacation",
        "days left in year", "longest working stretch (days)",
    ]
    names = [r[0] for r in rows[1:]]
    assert names == ["Alice", "Bob"]  # Alice's longer stretch ranks first


def test_burnout_csv_handles_employee_who_never_took_leave(db):
    set_policy(db)
    upsert_employee(db, "U_A", "Alice", None)
    rows = _csv_rows(build_burnout_csv(db, TODAY))
    alice = next(r for r in rows[1:] if r[0] == "Alice")
    # Stretch measured from the year start, not an error.
    assert int(alice[1]) == (TODAY - date(2026, 1, 1)).days
    assert int(alice[2]) == 10  # full vacation remaining (default allowance)


def _report_view(report_type, person=None):
    """A view_submission state payload matching build_report_modal."""
    return {
        "state": {
            "values": {
                "report_type": {REPORT_TYPE_ACTION: {"selected_option": {"value": report_type}}},
                "person": {"value": {"selected_option": {"value": person}}},
            }
        }
    }


def _block_ids(view):
    return {b.get("block_id") for b in view["blocks"]}


def test_report_modal_opens_with_picker_hidden(db):
    client = FakeSlackClient()
    ack = FakeAck()
    open_report(ack=ack, body={"user": {"id": "U_ADMIN"}, "trigger_id": "T"}, client=client, db=db, admin_ids=ADMINS)
    view = client.views_push_calls[0]["view"]
    assert view["callback_id"] == REPORT_CALLBACK_ID
    ids = _block_ids(view)
    assert "report_type" in ids
    assert "person" not in ids  # picker hidden until "history" is chosen


def test_report_modal_reveals_and_hides_employee_picker(db):
    upsert_employee(db, "U_A", "Alice", None)  # an employee to populate the dropdown
    client = FakeSlackClient()
    # Selecting "history" updates the modal in place to show the employee picker.
    update_report_modal(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}, "view": {"id": "V1"},
              "actions": [{"selected_option": {"value": "history"}}]},
        client=client,
        db=db,
        admin_ids=ADMINS,
    )
    assert client.views_update_calls[0]["view_id"] == "V1"
    person_block = next(
        b for b in client.views_update_calls[0]["view"]["blocks"] if b.get("block_id") == "person"
    )
    # It's a dropdown of employees (not a Slack user-picker, so no bots can appear).
    assert person_block["element"]["type"] == "static_select"
    assert [o["value"] for o in person_block["element"]["options"]] == ["U_A"]
    # Switching back to "quota" hides it again.
    update_report_modal(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}, "view": {"id": "V1"},
              "actions": [{"selected_option": {"value": "quota"}}]},
        client=client,
        db=db,
        admin_ids=ADMINS,
    )
    assert "person" not in _block_ids(client.views_update_calls[1]["view"])


def test_report_quota_dms_all_employee_csv(db):
    set_policy(db)
    upsert_employee(db, "U_A", "Alice", None)
    client = FakeSlackClient()
    ack = FakeAck()
    submit_report(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_report_view("quota"),
        db=db,
        client=client,
        admin_ids=ADMINS,
        today=TODAY,
    )
    assert ack.response == {"response_action": "clear"}  # modal closes on submit
    call = client.files_upload_v2_calls[0]
    assert call["channel"] == "U_ADMIN"  # the admin's DM
    assert call["content"].startswith("employee,leave type,used,remaining,carry-in")


def test_report_history_dms_that_persons_csv(db):
    set_policy(db)
    upsert_employee(db, "U_A", "Alice", None)
    rid = create_request(db, "U_A", "vacation", date(2026, 6, 10), date(2026, 6, 11), None)
    approve_request(db, rid)
    client = FakeSlackClient()
    ack = FakeAck()
    submit_report(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_report_view("history", person="U_A"),
        db=db,
        client=client,
        admin_ids=ADMINS,
        today=TODAY,
    )
    assert ack.response == {"response_action": "clear"}
    call = client.files_upload_v2_calls[0]
    assert call["channel"] == "U_ADMIN"
    # It's the history CSV (history header), and it's about Alice.
    assert call["content"].startswith("employee,leave type,start,end")
    assert "Alice" in call["content"] and "2026-06-10" in call["content"]


def test_report_modal_offers_burnout_option(db):
    client = FakeSlackClient()
    open_report(ack=FakeAck(), body={"user": {"id": "U_ADMIN"}, "trigger_id": "T"}, client=client, db=db, admin_ids=ADMINS)
    view = client.views_push_calls[0]["view"]
    block = next(b for b in view["blocks"] if b.get("block_id") == "report_type")
    values = {o["value"] for o in block["element"]["options"]}
    assert "burnout" in values


def test_report_burnout_dms_csv(db):
    set_policy(db)
    upsert_employee(db, "U_A", "Alice", None)
    client = FakeSlackClient()
    ack = FakeAck()
    submit_report(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_report_view("burnout"),
        db=db,
        client=client,
        admin_ids=ADMINS,
        today=TODAY,
    )
    assert ack.response == {"response_action": "clear"}  # no person picker needed
    call = client.files_upload_v2_calls[0]
    assert call["channel"] == "U_ADMIN"
    assert call["content"].startswith("employee,no-break stretch")


def test_report_history_without_person_is_rejected(db):
    set_policy(db)
    client = FakeSlackClient()
    ack = FakeAck()
    submit_report(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_report_view("history", person=None),
        db=db,
        client=client,
        admin_ids=ADMINS,
        today=TODAY,
    )
    assert ack.response["response_action"] == "errors"
    assert "person" in ack.response["errors"]
    assert client.files_upload_v2_calls == []


def test_report_non_admin_rejected(db):
    set_policy(db)
    upsert_employee(db, "U_A", "Alice", None)
    client = FakeSlackClient()
    ack = FakeAck()
    submit_report(
        ack=ack,
        body={"user": {"id": "U_OTHER"}},
        view=_report_view("quota"),
        db=db,
        client=client,
        admin_ids=ADMINS,
        today=TODAY,
    )
    assert ack.called
    assert client.files_upload_v2_calls == []


# --- Manage employees (#35) --------------------------------------------------


def _manage_block_ids(view):
    return {b.get("block_id") for b in view["blocks"]}


def test_manage_modal_opens_on_add_edit(db):
    client = FakeSlackClient()
    ack = FakeAck()
    open_manage_employees(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}, "trigger_id": "T"},
        client=client,
        admin_ids=ADMINS,
    )
    view = client.views_push_calls[0]["view"]
    assert view["callback_id"] == MANAGE_EMPLOYEES_CALLBACK_ID
    ids = _manage_block_ids(view)
    # Default action is Add/edit: employee + action + name + manager, no overrides.
    assert {"employee", "action", "name", "manager"} <= ids
    assert "override_sick" not in ids


def test_manage_modal_action_toggles_fields(db):
    client = FakeSlackClient()
    body = lambda action: {  # noqa: E731
        "user": {"id": "U_ADMIN"},
        "view": {"id": "V"},
        "actions": [{"selected_option": {"value": action}}],
    }
    # Override action -> the three override fields, no name/manager.
    update_manage_modal(ack=FakeAck(), body=body("override"), client=client, admin_ids=ADMINS)
    ids = _manage_block_ids(client.views_update_calls[0]["view"])
    assert "override_sick" in ids and "name" not in ids and "manager" not in ids
    # Delete action -> neither the add/edit fields nor overrides.
    update_manage_modal(ack=FakeAck(), body=body("delete"), client=client, admin_ids=ADMINS)
    ids2 = _manage_block_ids(client.views_update_calls[1]["view"])
    assert {"employee", "action"} <= ids2
    assert not ({"name", "manager", "override_sick"} & ids2)


def test_manage_add_creates_employee(db):
    client = FakeSlackClient()
    ack = FakeAck()
    submit_manage_employees(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_NEW", action="save", name="Newbie", manager="U_BOSS"),
        client=client,
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.response == {"response_action": "clear"}  # modal closes on success
    assert len(client.chat_postMessage_calls) == 1  # admin gets a confirmation DM
    emp = get_employee(db, "U_NEW")
    assert emp["real_name"] == "Newbie"
    assert emp["manager_id"] == "U_BOSS"
    assert "allowances" not in emp  # add/edit no longer sets an override


def test_manage_rejects_duplicate_name(db):
    upsert_employee(db, "U_A", "Alice", "U_A")
    ack = FakeAck()
    submit_manage_employees(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        # Case-insensitive clash with the existing "Alice".
        view=_manage_view("U_B", action="save", name="alice", manager="U_BOSS"),
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.response["response_action"] == "errors"
    assert "name" in ack.response["errors"]
    assert get_employee(db, "U_B") is None  # nothing created


def test_manage_edit_can_keep_own_name(db):
    upsert_employee(db, "U_E", "Eve", "U_MGR")
    ack = FakeAck()
    submit_manage_employees(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_E", action="save", name="Eve", manager="U_MGR2"),
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.response == {"response_action": "clear"}  # own name is not a clash
    assert get_employee(db, "U_E")["manager_id"] == "U_MGR2"


def test_manage_rejects_bot_as_employee(db):
    client = FakeSlackClient()
    client.bot_users = {"U_APP"}  # the leave-management app / Slackbot
    ack = FakeAck()
    submit_manage_employees(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_APP", action="save", name="Some App", manager="U_BOSS"),
        client=client,
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.response["response_action"] == "errors"
    assert "employee" in ack.response["errors"]
    assert get_employee(db, "U_APP") is None


def test_manage_rejects_bot_as_manager(db):
    client = FakeSlackClient()
    client.bot_users = {"U_APP"}
    ack = FakeAck()
    submit_manage_employees(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_NEW", action="save", name="Newbie2", manager="U_APP"),
        client=client,
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.response["response_action"] == "errors"
    assert "manager" in ack.response["errors"]
    assert get_employee(db, "U_NEW") is None


def test_manage_save_requires_a_manager(db):
    ack = FakeAck()
    submit_manage_employees(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_NEW", action="save", name="Newbie", manager=None),
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.response["response_action"] == "errors"
    assert "manager" in ack.response["errors"]
    assert get_employee(db, "U_NEW") is None


def test_manage_add_self_as_manager_marks_top_of_chain(db):
    # Picking the person as their own manager is how an admin marks top-of-chain;
    # their leave then auto-approves (see test_handlers).
    submit_manage_employees(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_TOP", action="save", name="Top", manager="U_TOP"),
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
    )
    assert get_employee(db, "U_TOP")["manager_id"] == "U_TOP"


def test_manage_override_action_sets_then_clears(db):
    upsert_employee(db, "U_A", "Alice", "U_A")
    # Set a vacation override.
    submit_manage_employees(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_A", action="override", overrides={"vacation": 15}),
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
    )
    emp = get_employee(db, "U_A")
    assert emp["allowances"] == {"vacation": 15}
    assert emp["real_name"] == "Alice" and emp["manager_id"] == "U_A"  # untouched
    # All blank clears the override (falls back to central policy).
    submit_manage_employees(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_A", action="override"),
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
    )
    assert "allowances" not in get_employee(db, "U_A")


def test_manage_edit_updates_name_and_manager(db):
    upsert_employee(db, "U_E", "Old Name", "U_OLD")
    submit_manage_employees(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_E", name="New Name", manager="U_NEW_MGR"),
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
    )
    emp = get_employee(db, "U_E")
    assert emp["real_name"] == "New Name"
    assert emp["manager_id"] == "U_NEW_MGR"


def test_manage_edit_manager_change_settles_pending_only(db):
    # Changing the manager strands a pending ticket (it sits in the OLD manager's DM,
    # but the approver check reads the new manager). So we withdraw pending requests
    # and DM the employee to re-file. Approved leave is unaffected and rides through.
    upsert_employee(db, "U_E", "Eve", "U_OLDMGR")
    pend = create_request(db, "U_E", "vacation", date(2026, 7, 1), date(2026, 7, 2), None)
    set_ticket_ref(db, pend, "C_OLD", "777.7")
    appr = create_request(db, "U_E", "vacation", date(2026, 8, 1), date(2026, 8, 2), None)
    approve_request(db, appr)
    set_calendar_event_id(db, appr, "evt-keep")
    cal, sheets, client = FakeCalendar(), FakeSheets(), FakeSlackClient()
    submit_manage_employees(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_E", action="save", name="Eve", manager="U_NEWMGR"),
        client=client,
        db=db,
        admin_ids=ADMINS,
        calendar=cal,
        sheets=sheets,
        today=TODAY,
    )
    assert get_employee(db, "U_E")["manager_id"] == "U_NEWMGR"  # change applied
    assert get_request(db, pend)["status"] == "cancelled"  # pending withdrawn
    assert get_request(db, appr)["status"] == "approved"  # approved rides through
    assert cal.deleted == []  # approved calendar event untouched
    assert any(
        c["channel"] == "C_OLD" and c["ts"] == "777.7" for c in client.chat_update_calls
    )  # old manager's ticket withdrawn
    assert any(
        c["channel"] == "U_E" and "re-file" in c["text"] for c in client.chat_postMessage_calls
    )  # employee told to re-file


def test_manage_edit_name_only_leaves_pending(db):
    # A name-only edit (manager unchanged) must NOT disturb pending leave.
    upsert_employee(db, "U_E", "Eve", "U_MGR")
    pend = create_request(db, "U_E", "vacation", date(2026, 7, 1), date(2026, 7, 2), None)
    set_ticket_ref(db, pend, "C", "1.1")
    cal, sheets, client = FakeCalendar(), FakeSheets(), FakeSlackClient()
    submit_manage_employees(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_E", action="save", name="Eve Renamed", manager="U_MGR"),
        client=client,
        db=db,
        admin_ids=ADMINS,
        calendar=cal,
        sheets=sheets,
        today=TODAY,
    )
    assert get_employee(db, "U_E")["real_name"] == "Eve Renamed"
    assert get_request(db, pend)["status"] == "pending"  # untouched
    assert client.chat_update_calls == []  # no ticket withdrawn


def test_manage_edit_preserves_carry_in(db):
    upsert_employee(db, "U_E", "Eve", None)
    # Materialise a carry chain so the row carries stored carry_in (2027 -> 5).
    remaining_balance(db, get_employee(db, "U_E"), "vacation", date(2026, 6, 1))
    remaining_balance(db, get_employee(db, "U_E"), "vacation", date(2027, 6, 1))
    before = get_employee(db, "U_E")["carry_in"]
    assert before["2027"] == 5

    # Editing name/manager must not clobber the stored carry_in.
    submit_manage_employees(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_E", name="Eve Renamed", manager="U_MGR"),
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
    )
    emp = get_employee(db, "U_E")
    assert emp["real_name"] == "Eve Renamed"
    assert emp["manager_id"] == "U_MGR"
    assert emp["carry_in"] == before


def test_manage_delete_non_manager_succeeds(db):
    upsert_employee(db, "U_A", "Alice", None)
    submit_manage_employees(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_A", action="delete"),
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
    )
    assert get_employee(db, "U_A") is None


def test_manage_delete_manager_blocked_naming_reports(db):
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_R", "Reportee", "U_M")
    ack = FakeAck()
    submit_manage_employees(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_M", action="delete"),
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.response["response_action"] == "errors"
    assert "Reportee" in ack.response["errors"]["employee"]
    # Nothing deleted, no one re-parented.
    assert get_employee(db, "U_M") is not None
    assert get_employee(db, "U_R")["manager_id"] == "U_M"


def test_manage_delete_settles_pending_leave(db):
    # Deleting an employee with a pending request cancels it and withdraws the
    # manager's still-open ticket, so no dangling Approve/Decline buttons remain.
    upsert_employee(db, "U_M", "Manager", "U_M")
    upsert_employee(db, "U_R", "Reportee", "U_M")
    rid = create_request(db, "U_R", "vacation", date(2026, 7, 1), date(2026, 7, 2), None)
    set_ticket_ref(db, rid, "C_MGR", "555.5")
    cal, sheets, client = FakeCalendar(), FakeSheets(), FakeSlackClient()
    submit_manage_employees(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_R", action="delete"),
        client=client,
        db=db,
        admin_ids=ADMINS,
        calendar=cal,
        sheets=sheets,
        today=TODAY,
    )
    assert get_employee(db, "U_R") is None  # removed
    assert get_request(db, rid)["status"] == "cancelled"  # pending leave settled
    assert any(
        c["channel"] == "C_MGR" and c["ts"] == "555.5" for c in client.chat_update_calls
    )  # ticket withdrawn


def test_manage_delete_settles_future_approved_leave(db):
    # An approved upcoming leave has its calendar event and board entry removed.
    upsert_employee(db, "U_A", "Alice", "U_A")
    rid = create_request(db, "U_A", "vacation", date(2026, 7, 1), date(2026, 7, 2), None)
    approve_request(db, rid)
    set_calendar_event_id(db, rid, "evt-future")
    cal, sheets, client = FakeCalendar(), FakeSheets(), FakeSlackClient()
    submit_manage_employees(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_A", action="delete"),
        client=client,
        db=db,
        admin_ids=ADMINS,
        calendar=cal,
        sheets=sheets,
        today=TODAY,
    )
    assert get_employee(db, "U_A") is None
    assert get_request(db, rid)["status"] == "cancelled"
    assert cal.deleted == ["evt-future"]  # calendar event removed


def test_manage_delete_after_reassigning_reports_succeeds(db):
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_R", "Reportee", "U_M")
    # Re-assign the report to someone else via the edit flow.
    submit_manage_employees(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_R", name="Reportee", manager="U_OTHER"),
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
    )
    ack = FakeAck()
    submit_manage_employees(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_M", action="delete"),
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.response == {"response_action": "clear"}
    assert get_employee(db, "U_M") is None


def _holidays_view(holiday_date=None, label=None, remove=None):
    """A view_submission state payload matching build_holidays_modal."""
    return {
        "state": {
            "values": {
                "holiday_date": {"value": {"selected_date": holiday_date}},
                "holiday_label": {"value": {"value": label}},
                "holiday_remove": {
                    "value": {"selected_option": {"value": remove}} if remove else {}
                },
            }
        }
    }


def test_holidays_modal_opens_for_admin(db):
    upsert_holiday(db, date(2026, 4, 13), "Songkran")
    client = FakeSlackClient()
    open_holidays(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}, "trigger_id": "T"},
        client=client,
        db=db,
        admin_ids=ADMINS,
    )
    view = client.views_push_calls[0]["view"]
    assert view["callback_id"] == HOLIDAYS_CALLBACK_ID
    ids = {b.get("block_id") for b in view["blocks"]}
    assert {"holiday_date", "holiday_label", "holiday_remove"} <= ids  # remove shown (one exists)


def test_holidays_add_creates_event_and_stores(db):
    cal = FakeCalendar()
    ack = FakeAck()
    submit_holidays(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_holidays_view(holiday_date="2026-04-13", label="Songkran"),
        db=db,
        calendar=cal,
        client=FakeSlackClient(),
        admin_ids=ADMINS,
    )
    assert ack.response == {"response_action": "clear"}
    assert holidays_for_year(db, 2026) == {date(2026, 4, 13)}
    assert get_holiday(db, date(2026, 4, 13))["calendar_event_id"] == cal.created[0]["id"]
    assert "Songkran" in cal.created[0]["summary"]


def test_holidays_remove_deletes_event_and_entry(db):
    cal = FakeCalendar()
    upsert_holiday(db, date(2026, 4, 13), "Songkran", calendar_event_id="evt9")
    submit_holidays(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_holidays_view(remove="2026-04-13"),
        db=db,
        calendar=cal,
        client=FakeSlackClient(),
        admin_ids=ADMINS,
    )
    assert holidays_for_year(db, 2026) == set()
    assert cal.deleted == ["evt9"]


def test_holidays_add_requires_date_and_label(db):
    cal = FakeCalendar()
    ack = FakeAck()
    submit_holidays(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_holidays_view(holiday_date="2026-04-13"),  # label missing
        db=db,
        calendar=cal,
        client=FakeSlackClient(),
        admin_ids=ADMINS,
    )
    assert ack.response["response_action"] == "errors"
    assert "holiday_label" in ack.response["errors"]
    assert holidays_for_year(db, 2026) == set()
    assert cal.created == []


def test_holidays_non_admin_submit_rejected(db):
    cal = FakeCalendar()
    submit_holidays(
        ack=FakeAck(),
        body={"user": {"id": "U_OTHER"}},
        view=_holidays_view(holiday_date="2026-04-13", label="Songkran"),
        db=db,
        calendar=cal,
        client=FakeSlackClient(),
        admin_ids=ADMINS,
    )
    assert holidays_for_year(db, 2026) == set()
    assert cal.created == []


def test_manage_non_admin_submit_rejected(db):
    submit_manage_employees(
        ack=FakeAck(),
        body={"user": {"id": "U_OTHER"}},
        view=_manage_view("U_NEW", name="X"),
        client=FakeSlackClient(),
        db=db,
        admin_ids=ADMINS,
    )
    assert get_employee(db, "U_NEW") is None
