from datetime import date

from leave.board import get_board, grid_rows, reset_board, update_board
from leave.db import get_employee
from leave.handlers import handle_approve, submit_cancel
from leave.requests import approve_request, create_request, set_calendar_event_id
from leave.seed import upsert_employee
from tests.fakes import FakeAck, FakeCalendar, FakeSheets, FakeSlackClient, make_action_body, make_cancel_view


def _entries(**by_id):
    return by_id


def test_grid_rows_groups_by_person_with_type_and_half():
    entries = {
        "r1": {"name": "Alice", "type": "vacation", "half": None, "start": "2026-06-10", "end": "2026-06-11"},
        "r2": {"name": "Bob", "type": "sick", "half": "morning", "start": "2026-06-12", "end": "2026-06-12"},
    }
    rows = grid_rows(entries, 2026, 6)
    by_name = {r["name"]: r["cells"] for r in rows}
    assert by_name["Alice"][10] == {"type": "vacation", "half": None}
    assert by_name["Alice"][11] == {"type": "vacation", "half": None}
    assert by_name["Bob"][12] == {"type": "sick", "half": "morning"}


def test_grid_rows_excludes_other_months():
    entries = {"r1": {"name": "Alice", "type": "vacation", "half": None, "start": "2026-07-01", "end": "2026-07-02"}}
    assert grid_rows(entries, 2026, 6) == []


def _add(rid, name, ltype, start, end, half=None):
    return {"request_id": rid, "name": name, "type": ltype, "start": start, "end": end, "half": half}


def test_update_renders_sheet_and_posts_link(db, monkeypatch):
    monkeypatch.setenv("LEAVE_BOARD_CHANNEL", "C_BOARD")
    monkeypatch.setenv("LEAVE_SHEET_ID", "SHEET123")
    client, sheets = FakeSlackClient(), FakeSheets()

    update_board(db, client, date(2026, 6, 15), sheets, add=_add("r1", "Alice", "vacation", date(2026, 6, 10), date(2026, 6, 11)))

    assert len(sheets.renders) == 1
    rendered_names = {r["name"] for r in sheets.renders[0]["rows"]}
    assert "Alice" in rendered_names
    assert client.chat_postMessage_calls[0]["channel"] == "C_BOARD"
    assert "SHEET123" in client.chat_postMessage_calls[0]["text"]
    assert "r1" in get_board(db)["entries"]


def test_month_rollover_resets_entries(db, monkeypatch):
    monkeypatch.setenv("LEAVE_BOARD_CHANNEL", "C_BOARD")
    monkeypatch.setenv("LEAVE_SHEET_ID", "SHEET123")
    client, sheets = FakeSlackClient(), FakeSheets()
    update_board(db, client, date(2026, 6, 15), sheets, add=_add("r1", "Alice", "vacation", date(2026, 6, 10), date(2026, 6, 11)))
    update_board(db, client, date(2026, 7, 1), sheets, add=_add("r2", "Bob", "sick", date(2026, 7, 2), date(2026, 7, 3)))
    board = get_board(db)
    assert board["month"] == "2026-07" and "r1" not in board["entries"]


def test_cancel_removes_entry(db, monkeypatch):
    monkeypatch.setenv("LEAVE_BOARD_CHANNEL", "C_BOARD")
    monkeypatch.setenv("LEAVE_SHEET_ID", "SHEET123")
    client, sheets = FakeSlackClient(), FakeSheets()
    update_board(db, client, date(2026, 6, 15), sheets, add=_add("r1", "Alice", "vacation", date(2026, 6, 10), date(2026, 6, 11)))
    update_board(db, client, date(2026, 6, 16), sheets, remove_request_id="r1")
    assert "r1" not in get_board(db)["entries"]


def test_board_disabled_without_channel(db, monkeypatch):
    monkeypatch.delenv("LEAVE_BOARD_CHANNEL", raising=False)  # hermetic vs a local .env
    monkeypatch.setenv("LEAVE_SHEET_ID", "SHEET123")
    client, sheets = FakeSlackClient(), FakeSheets()
    update_board(db, client, date(2026, 6, 15), sheets, add=_add("r1", "Alice", "vacation", date(2026, 6, 10), date(2026, 6, 11)))
    assert sheets.renders == [] and client.chat_postMessage_calls == []
    assert get_board(db) is None


def test_reset_board_clears_state_and_blanks_sheet(db, monkeypatch):
    monkeypatch.setenv("LEAVE_BOARD_CHANNEL", "C_BOARD")
    monkeypatch.setenv("LEAVE_SHEET_ID", "SHEET123")
    client, sheets = FakeSlackClient(), FakeSheets()
    update_board(db, client, date(2026, 6, 15), sheets, add=_add("r1", "Alice", "vacation", date(2026, 6, 10), date(2026, 6, 11)))
    assert get_board(db) is not None

    reset_board(db, sheets, date(2026, 6, 15))

    assert get_board(db) is None  # saved state dropped
    assert sheets.renders[-1]["rows"] == []  # sheet blanked


class _RaisingSheets:
    def render_grid(self, *args, **kwargs):
        raise RuntimeError("sheets unavailable")


def test_board_failure_is_swallowed(db, monkeypatch):
    # A Sheets/board error must never propagate (it would break/slow the leave request).
    monkeypatch.setenv("LEAVE_BOARD_CHANNEL", "C_BOARD")
    monkeypatch.setenv("LEAVE_SHEET_ID", "SHEET123")
    client = FakeSlackClient()
    update_board(db, client, date(2026, 6, 15), _RaisingSheets(), add=_add("r1", "Alice", "vacation", date(2026, 6, 10), date(2026, 6, 11)))
    # No exception; nothing posted or saved because the render failed first.
    assert client.chat_postMessage_calls == []
    assert get_board(db) is None


def test_board_disabled_without_sheets_client(db, monkeypatch):
    monkeypatch.setenv("LEAVE_BOARD_CHANNEL", "C_BOARD")
    client = FakeSlackClient()
    update_board(db, client, date(2026, 6, 15), None, add=_add("r1", "Alice", "vacation", date(2026, 6, 10), date(2026, 6, 11)))
    assert client.chat_postMessage_calls == [] and get_board(db) is None


def test_approve_renders_board(db, monkeypatch):
    monkeypatch.setenv("LEAVE_BOARD_CHANNEL", "C_BOARD")
    monkeypatch.setenv("LEAVE_SHEET_ID", "SHEET123")
    upsert_employee(db, "U_BOSS", "Boss", None)
    upsert_employee(db, "U_A", "Alice", "U_BOSS")
    rid = create_request(db, "U_A", "vacation", date(2026, 6, 20), date(2026, 6, 21), None)
    client, cal, sheets = FakeSlackClient(), FakeCalendar(), FakeSheets()

    handle_approve(FakeAck(), make_action_body(rid, "U_BOSS"), client, db, cal, sheets, today=date(2026, 6, 15))

    assert len(sheets.renders) == 1
    assert rid in get_board(db)["entries"]
    assert any(c["channel"] == "C_BOARD" for c in client.chat_postMessage_calls)


def test_cancel_approved_removes_from_board(db, monkeypatch):
    monkeypatch.setenv("LEAVE_BOARD_CHANNEL", "C_BOARD")
    monkeypatch.setenv("LEAVE_SHEET_ID", "SHEET123")
    upsert_employee(db, "U_A", "Alice", None)
    rid = create_request(db, "U_A", "vacation", date(2026, 6, 20), date(2026, 6, 21), None)
    approve_request(db, rid)
    set_calendar_event_id(db, rid, "evtX")
    client, sheets = FakeSlackClient(), FakeSheets()
    update_board(db, client, date(2026, 6, 15), sheets, add=_add(rid, "Alice", "vacation", date(2026, 6, 20), date(2026, 6, 21)))

    submit_cancel(FakeAck(), {"user": {"id": "U_A"}}, make_cancel_view(rid), client, db, FakeCalendar(), sheets, today=date(2026, 6, 15))

    assert rid not in get_board(db)["entries"]
