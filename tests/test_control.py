import csv
import io
from datetime import date

from leave.blocks import (
    CARRY_OVER_CALLBACK_ID,
    CLEAR_CALLBACK_ID,
    CONTROL_MENU_CALLBACK_ID,
    LEAVE_LIMITS_ACTION,
    LEAVE_LIMITS_CALLBACK_ID,
    MANAGE_EMPLOYEES_CALLBACK_ID,
    REPORT_ACTION,
    SETTINGS_VIEW_CALLBACK_ID,
    VIEW_SETTINGS_ACTION,
)
from leave.board import BOARD_KEY, get_board
from leave.db import get_employee
from leave.handlers import (
    NOT_ADMIN,
    handle_report,
    is_admin,
    open_carry_over,
    open_clear,
    open_control_menu,
    open_leave_limits,
    open_manage_employees,
    open_view_settings,
    submit_carry_over,
    submit_clear,
    submit_leave_limits,
    submit_manage_employees,
)
from leave.holidays import holidays_for_year, upsert_holiday
from leave.report import build_report_csv
from leave.policy import POLICY_KEY, get_policy, set_policy
from leave.requests import (
    approve_request,
    create_request,
    get_request,
    recompute_all_carry_in,
    remaining_balance,
    remaining_balances,
    set_calendar_event_id,
)
from leave.seed import upsert_employee
from tests.fakes import FakeAck, FakeCalendar, FakeSheets, FakeSlackClient

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
        "action": {"value": {"selected_option": {"value": action}}},
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
    cal, sheets, ack = FakeCalendar(), FakeSheets(), FakeAck()
    submit_clear(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_clear_view("CLEAR"),
        db=db,
        calendar=cal,
        sheets=sheets,
        admin_ids=ADMINS,
        today=TODAY,
    )
    assert ack.called and ack.response is None
    # Requests gone, their calendar events deleted, board reset.
    assert get_request(db, r1) is None and get_request(db, r2) is None
    assert set(cal.deleted) == {"evt1", "evt2"}
    assert get_board(db) is None
    # Employees, central policy, and holidays kept.
    assert get_employee(db, "U_A") is not None
    assert get_policy(db)["allowances"]["vacation"] == 10
    assert date(2026, 1, 1) in holidays_for_year(db, 2026)


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
        admin_ids=ADMINS,
        today=TODAY,
    )
    assert ack.called
    assert get_request(db, rid) is not None
    assert cal.deleted == []


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


def test_report_uploads_csv_to_admin_dm(db):
    set_policy(db)
    upsert_employee(db, "U_A", "Alice", None)
    client = FakeSlackClient()
    ack = FakeAck()
    handle_report(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        client=client,
        db=db,
        admin_ids=ADMINS,
        today=TODAY,
    )
    assert ack.called
    assert len(client.files_upload_v2_calls) == 1
    call = client.files_upload_v2_calls[0]
    # Uploaded to the admin's DM (opened for that user), not a shared channel.
    assert call["channel"] == "D_U_ADMIN"
    assert client.conversations_open_calls[0]["users"] == "U_ADMIN"
    assert call["content"].startswith("employee,leave type,used,remaining,carry-in")
    assert "Alice" in call["content"]


def test_report_non_admin_rejected(db):
    set_policy(db)
    upsert_employee(db, "U_A", "Alice", None)
    client = FakeSlackClient()
    ack = FakeAck()
    handle_report(
        ack=ack,
        body={"user": {"id": "U_OTHER"}},
        client=client,
        db=db,
        admin_ids=ADMINS,
        today=TODAY,
    )
    assert ack.called
    assert client.files_upload_v2_calls == []


# --- Manage employees (#35) --------------------------------------------------


def test_manage_modal_opens_for_admin(db):
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
    assert any(b.get("block_id") == "employee" for b in view["blocks"])


def test_manage_add_creates_employee_with_override(db):
    ack = FakeAck()
    submit_manage_employees(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_NEW", name="Newbie", manager="U_BOSS", overrides={"vacation": 15}),
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.called and ack.response is None
    emp = get_employee(db, "U_NEW")
    assert emp["real_name"] == "Newbie"
    assert emp["manager_id"] == "U_BOSS"
    assert emp["allowances"] == {"vacation": 15}


def test_manage_edit_updates_name_and_manager(db):
    upsert_employee(db, "U_E", "Old Name", "U_OLD")
    submit_manage_employees(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_E", name="New Name", manager="U_NEW_MGR"),
        db=db,
        admin_ids=ADMINS,
    )
    emp = get_employee(db, "U_E")
    assert emp["real_name"] == "New Name"
    assert emp["manager_id"] == "U_NEW_MGR"


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
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.response["response_action"] == "errors"
    assert "Reportee" in ack.response["errors"]["employee"]
    # Nothing deleted, no one re-parented.
    assert get_employee(db, "U_M") is not None
    assert get_employee(db, "U_R")["manager_id"] == "U_M"


def test_manage_delete_after_reassigning_reports_succeeds(db):
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_R", "Reportee", "U_M")
    # Re-assign the report to someone else via the edit flow.
    submit_manage_employees(
        ack=FakeAck(),
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_R", name="Reportee", manager="U_OTHER"),
        db=db,
        admin_ids=ADMINS,
    )
    ack = FakeAck()
    submit_manage_employees(
        ack=ack,
        body={"user": {"id": "U_ADMIN"}},
        view=_manage_view("U_M", action="delete"),
        db=db,
        admin_ids=ADMINS,
    )
    assert ack.response is None
    assert get_employee(db, "U_M") is None


def test_manage_non_admin_submit_rejected(db):
    submit_manage_employees(
        ack=FakeAck(),
        body={"user": {"id": "U_OTHER"}},
        view=_manage_view("U_NEW", name="X"),
        db=db,
        admin_ids=ADMINS,
    )
    assert get_employee(db, "U_NEW") is None
