from datetime import date

from leave.board import build_board_blocks, get_board, update_board
from leave.db import get_employee
from leave.handlers import handle_approve, submit_cancel
from leave.requests import approve_request, create_request, set_calendar_event_id
from leave.seed import upsert_employee
from tests.fakes import FakeAck, FakeCalendar, FakeSlackClient, make_action_body, make_cancel_view


def test_build_board_blocks_has_header_and_person():
    blocks = build_board_blocks("June 2026", 30, [{"name": "Alice", "cells": {10: "#"}}], {13})
    assert blocks[0]["type"] == "header"
    assert "June 2026" in blocks[0]["text"]["text"]
    section_text = " ".join(
        b["text"]["text"] for b in blocks if b["type"] == "section"
    )
    assert "Ali" in section_text  # the person's row is rendered


def _add(rid, name, start, end, half=None):
    return {"request_id": rid, "name": name, "start": start, "end": end, "half": half}


def test_first_update_posts_board(db, monkeypatch):
    monkeypatch.setenv("LEAVE_BOARD_CHANNEL", "C_BOARD")
    client = FakeSlackClient()
    update_board(db, client, date(2026, 6, 15), add=_add("r1", "Alice", date(2026, 6, 10), date(2026, 6, 11)))
    assert len(client.chat_postMessage_calls) == 1
    assert client.chat_postMessage_calls[0]["channel"] == "C_BOARD"
    board = get_board(db)
    assert board["month"] == "2026-06" and "r1" in board["entries"]


def test_second_change_edits_in_place(db, monkeypatch):
    monkeypatch.setenv("LEAVE_BOARD_CHANNEL", "C_BOARD")
    client = FakeSlackClient()
    update_board(db, client, date(2026, 6, 15), add=_add("r1", "Alice", date(2026, 6, 10), date(2026, 6, 11)))
    update_board(db, client, date(2026, 6, 16), add=_add("r2", "Bob", date(2026, 6, 20), date(2026, 6, 20), "morning"))
    assert len(client.chat_postMessage_calls) == 1  # no second post
    assert len(client.chat_update_calls) == 1
    assert client.chat_update_calls[0]["channel"] == "C_BOARD"
    assert set(get_board(db)["entries"]) == {"r1", "r2"}


def test_month_rollover_posts_fresh(db, monkeypatch):
    monkeypatch.setenv("LEAVE_BOARD_CHANNEL", "C_BOARD")
    client = FakeSlackClient()
    update_board(db, client, date(2026, 6, 15), add=_add("r1", "Alice", date(2026, 6, 10), date(2026, 6, 11)))
    update_board(db, client, date(2026, 7, 1), add=_add("r2", "Bob", date(2026, 7, 2), date(2026, 7, 3)))
    assert len(client.chat_postMessage_calls) == 2  # fresh message for July
    board = get_board(db)
    assert board["month"] == "2026-07" and "r1" not in board["entries"]


def test_cancel_removes_entry(db, monkeypatch):
    monkeypatch.setenv("LEAVE_BOARD_CHANNEL", "C_BOARD")
    client = FakeSlackClient()
    update_board(db, client, date(2026, 6, 15), add=_add("r1", "Alice", date(2026, 6, 10), date(2026, 6, 11)))
    update_board(db, client, date(2026, 6, 16), remove_request_id="r1")
    assert "r1" not in get_board(db)["entries"]


def test_board_disabled_without_channel(db):
    client = FakeSlackClient()
    update_board(db, client, date(2026, 6, 15), add=_add("r1", "Alice", date(2026, 6, 10), date(2026, 6, 11)))
    assert client.chat_postMessage_calls == []
    assert get_board(db) is None


def test_approve_posts_to_board(db, monkeypatch):
    monkeypatch.setenv("LEAVE_BOARD_CHANNEL", "C_BOARD")
    upsert_employee(db, "U_BOSS", "Boss", None)
    upsert_employee(db, "U_A", "Alice", "U_BOSS")
    rid = create_request(db, "U_A", "vacation", date(2026, 6, 20), date(2026, 6, 21), None)
    client, cal = FakeSlackClient(), FakeCalendar()

    handle_approve(FakeAck(), make_action_body(rid, "U_BOSS"), client, db, cal, today=date(2026, 6, 15))

    assert any(c["channel"] == "C_BOARD" for c in client.chat_postMessage_calls)
    assert rid in get_board(db)["entries"]


def test_cancel_approved_removes_from_board(db, monkeypatch):
    monkeypatch.setenv("LEAVE_BOARD_CHANNEL", "C_BOARD")
    upsert_employee(db, "U_A", "Alice", None)
    rid = create_request(db, "U_A", "vacation", date(2026, 6, 20), date(2026, 6, 21), None)
    approve_request(db, rid)
    set_calendar_event_id(db, rid, "evtX")
    client = FakeSlackClient()
    update_board(db, client, date(2026, 6, 15), add=_add(rid, "Alice", date(2026, 6, 20), date(2026, 6, 21)))

    submit_cancel(FakeAck(), {"user": {"id": "U_A"}}, make_cancel_view(rid), client, db, FakeCalendar(), today=date(2026, 6, 15))

    assert rid not in get_board(db)["entries"]
