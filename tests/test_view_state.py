"""Pure readers for the Slack view-submission envelope — plain dicts, no Slack."""

from leave.view_state import checkbox_on, date_str, option, text, user, users


def test_text_reads_plain_input():
    values = {"reason": {"value": {"value": "back Monday"}}}
    assert text(values, "reason") == "back Monday"


def test_option_reads_selected_value():
    values = {"leave_type": {"value": {"selected_option": {"value": "vacation"}}}}
    assert option(values, "leave_type") == "vacation"


def test_date_str_reads_iso_string():
    values = {"start_date": {"value": {"selected_date": "2026-07-02"}}}
    assert date_str(values, "start_date") == "2026-07-02"


def test_user_and_users():
    assert user({"person": {"value": {"selected_user": "U1"}}}, "person") == "U1"
    assert users({"people": {"value": {"selected_users": ["U1", "U2"]}}}, "people") == ["U1", "U2"]


def test_checkbox_on_reflects_selection():
    on = {"enable": {"value": {"selected_options": [{"value": "yes"}]}}}
    assert checkbox_on(on, "enable") is True
    assert checkbox_on({"enable": {"value": {}}}, "enable") is False


def test_action_id_override():
    values = {"report_type": {"pick_report": {"selected_option": {"value": "history"}}}}
    assert option(values, "report_type", "pick_report") == "history"


def test_absent_fields_default_safely():
    assert text({}, "missing") is None
    assert option({}, "missing") is None
    assert date_str({}, "missing") is None
    assert user({}, "missing") is None
    assert users({}, "missing") == []
    assert checkbox_on({}, "missing") is False
