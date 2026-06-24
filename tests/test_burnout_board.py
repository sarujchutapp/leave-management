"""/burnout board — a manager's direct reports ranked by burnout risk.

The signal/ranking logic is exercised through the moto `db` fixture (prior art:
the burnout CSV tests); the command + manager gate are exercised at the handler
seam with the Slack fakes (prior art: the report handler tests).
"""

from datetime import date

from leave.db import get_employee
from leave.handlers import NOT_A_MANAGER, open_burnout
from leave.holidays import upsert_holiday
from leave.policy import set_policy
from leave.report import build_burnout_csv, ranked_burnout_signals
from leave.requests import approve_request, create_request
from leave.seed import upsert_employee
from tests.fakes import FakeAck, FakeSlackClient

TODAY = date(2026, 6, 8)


def _approved_past_leave(db, emp_id, start, end):
    """An approved leave that has already ended (a 'taken' break)."""
    rid = create_request(db, emp_id, "vacation", start, end, None)
    approve_request(db, rid)
    return rid


def _command(user_id):
    """A slash-command body (e.g. /burnout), which carries user_id directly."""
    return {"user_id": user_id}


def _board_text(client):
    """The concatenated mrkdwn of the board DM the bot posted to the caller."""
    blocks = client.chat_postMessage_calls[0]["blocks"]
    return "\n".join(b["text"]["text"] for b in blocks)


def test_ranked_signals_order_by_no_break_stretch_longest_first(db):
    set_policy(db)
    upsert_employee(db, "U_A", "Alice", None)
    upsert_employee(db, "U_B", "Bob", None)
    _approved_past_leave(db, "U_A", date(2026, 2, 2), date(2026, 2, 2))  # long dry spell
    _approved_past_leave(db, "U_B", date(2026, 5, 29), date(2026, 5, 29))  # short
    signals = ranked_burnout_signals(db, [get_employee(db, "U_B"), get_employee(db, "U_A")], TODAY)
    assert [s.name for s in signals] == ["Alice", "Bob"]  # longest stretch first, not input order
    assert signals[0].stretch > signals[1].stretch


def test_manager_sees_direct_reports_ranked_with_explainable_flags(db):
    set_policy(db)
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_A", "Alice", "U_M")
    upsert_employee(db, "U_B", "Bob", "U_M")
    _approved_past_leave(db, "U_A", date(2026, 2, 2), date(2026, 2, 2))
    _approved_past_leave(db, "U_B", date(2026, 5, 29), date(2026, 5, 29))
    client, ack = FakeSlackClient(), FakeAck()

    open_burnout(ack=ack, body=_command("U_M"), db=db, client=client, today=TODAY)

    assert ack.called
    assert client.chat_postMessage_calls[0]["channel"] == "U_M"  # DMed to the manager
    text = _board_text(client)
    assert text.index("Alice") < text.index("Bob")  # longest no-break stretch ranks first
    # The supporting flags are spelled out — never an opaque score.
    assert "days since last leave" in text
    assert "days left in the year" in text
    assert "longest working stretch" in text


def test_caller_who_manages_no_one_gets_clear_reply(db):
    set_policy(db)
    upsert_employee(db, "U_SOLO", "Solo", None)  # manages nobody
    client, ack = FakeSlackClient(), FakeAck()

    open_burnout(ack=ack, body=_command("U_SOLO"), db=db, client=client, today=TODAY)

    assert ack.response == NOT_A_MANAGER
    assert client.chat_postMessage_calls == []  # no empty board posted


def test_self_managed_caller_is_not_a_manager(db):
    # Own manager = top of chain; they don't report to themselves, so the board is empty.
    set_policy(db)
    upsert_employee(db, "U_SELF", "Selfie", "U_SELF")
    client, ack = FakeSlackClient(), FakeAck()

    open_burnout(ack=ack, body=_command("U_SELF"), db=db, client=client, today=TODAY)

    assert ack.response == NOT_A_MANAGER
    assert client.chat_postMessage_calls == []


def test_board_scoped_to_callers_direct_reports_only(db):
    set_policy(db)
    upsert_employee(db, "U_M1", "ManagerOne", None)
    upsert_employee(db, "U_M2", "ManagerTwo", None)
    upsert_employee(db, "U_A", "Alice", "U_M1")  # ManagerOne's report
    upsert_employee(db, "U_Z", "Zoe", "U_M2")  # ManagerTwo's report
    client = FakeSlackClient()

    open_burnout(ack=FakeAck(), body=_command("U_M1"), db=db, client=client, today=TODAY)

    text = _board_text(client)
    assert "Alice" in text
    assert "Zoe" not in text  # another manager's report never appears


def test_reserved_and_config_items_excluded(db):
    set_policy(db)  # creates the reserved policy item in the employees table
    upsert_holiday(db, date(2026, 12, 31), "New Year's Eve")  # reserved holidays item
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_A", "Alice", "U_M")
    client = FakeSlackClient()

    open_burnout(ack=FakeAck(), body=_command("U_M"), db=db, client=client, today=TODAY)

    # One header section + exactly one report row (Alice); no reserved item leaks in.
    blocks = client.chat_postMessage_calls[0]["blocks"]
    assert len(blocks) == 2
    assert "Alice" in blocks[1]["text"]["text"]


def test_report_who_never_took_leave_is_handled(db):
    set_policy(db)
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_A", "Alice", "U_M")  # never took leave
    client = FakeSlackClient()

    open_burnout(ack=FakeAck(), body=_command("U_M"), db=db, client=client, today=TODAY)

    # Stretch measured from a defined start (year start), not an error.
    signals = ranked_burnout_signals(db, [get_employee(db, "U_A")], TODAY)
    assert signals[0].stretch == (TODAY - date(2026, 1, 1)).days
    assert "Alice" in _board_text(client)


def test_board_and_csv_compute_the_same_signals(db):
    # The board and the /control burnout CSV share one computation, so a row's
    # numbers must match between them — they cannot drift.
    set_policy(db)
    upsert_employee(db, "U_M", "Manager", None)
    upsert_employee(db, "U_A", "Alice", "U_M")
    _approved_past_leave(db, "U_A", date(2026, 2, 2), date(2026, 2, 2))

    board = next(s for s in ranked_burnout_signals(db, [get_employee(db, "U_A")], TODAY) if s.name == "Alice")
    csv_row = next(line for line in build_burnout_csv(db, TODAY).splitlines() if line.startswith("Alice"))
    assert csv_row.split(",") == [
        "Alice",
        str(board.stretch),
        str(board.remaining),
        str(board.days_left),
        str(board.working),
    ]
