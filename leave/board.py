"""The shared leave board, now rendered into a Google Sheet (people x days grid,
coloured by leave type). Slack just gets a short "updated" message with a link.

Denormalized by design (see issue #28 / ADR-0001's no-scan stance): the month's
approved leave is kept as a reserved `__board__` item in the employees table
(channel, month, entries) and updated incrementally from the approve/cancel
handlers — no cross-employee scan. The sheet is rebuilt from that state on each
change. Disabled (no-op) unless both LEAVE_BOARD_CHANNEL and a sheets client are
present.
"""

import logging
import os
from calendar import monthrange
from datetime import date, timedelta

logger = logging.getLogger(__name__)

BOARD_KEY = "__board__"


def get_board(db):
    return db.employees.get_item(Key={"slack_user_id": BOARD_KEY}).get("Item")


def _save_board(db, channel, month, entries):
    db.employees.update_item(
        Key={"slack_user_id": BOARD_KEY},
        UpdateExpression="SET channel = :c, #m = :m, entries = :e",
        ExpressionAttributeNames={"#m": "month"},
        ExpressionAttributeValues={":c": channel, ":m": month, ":e": entries},
    )


def grid_rows(entries, year, month):
    """Build [{name, cells: {day -> {type, half}}}] for the month from board entries,
    grouped by person. Each leave day gets its type; a half-day carries its half."""
    first = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])
    by_name = {}
    for e in entries.values():
        start, end = date.fromisoformat(e["start"]), date.fromisoformat(e["end"])
        if start > last or end < first:
            continue
        cells = by_name.setdefault(e["name"], {})
        if e.get("half"):
            cells[start.day] = {"type": e["type"], "half": e["half"]}
        else:
            d = max(start, first)
            while d <= min(end, last):
                cells[d.day] = {"type": e["type"], "half": None}
                d += timedelta(days=1)
    return [{"name": n, "cells": c} for n, c in sorted(by_name.items())]


def _sheet_url():
    sid = os.environ.get("LEAVE_SHEET_ID")
    return f"https://docs.google.com/spreadsheets/d/{sid}/edit" if sid else None


def _change_text(add, remove_request_id):
    if add:
        half = f" ({add['half']})" if add.get("half") else ""
        return f"✅ {add['name']} — {add['type']} {add['start']} → {add['end']}{half}"
    if remove_request_id:
        return "↩️ A leave was cancelled"
    return "Leave board updated"


def update_board(db, client, today, sheets, *, add=None, remove_request_id=None):
    """Apply one change to the board state, re-render the sheet, and post a link to
    Slack. No-op unless a channel and a sheets client are both configured."""
    channel = os.environ.get("LEAVE_BOARD_CHANNEL")
    if not channel or sheets is None:
        return

    # The board is best-effort: a Sheets/Slack hiccup must never break or slow the
    # leave request itself, so swallow and log rather than propagate.
    try:
        month = f"{today.year:04d}-{today.month:02d}"
        board = get_board(db)
        same_month = board is not None and board.get("month") == month
        entries = dict(board.get("entries") or {}) if same_month else {}

        if add:
            entries[add["request_id"]] = {
                "name": add["name"],
                "type": add["type"],
                "half": add.get("half"),
                "start": add["start"].isoformat(),
                "end": add["end"].isoformat(),
            }
        if remove_request_id:
            entries.pop(remove_request_id, None)

        num_days = monthrange(today.year, today.month)[1]
        sheets.render_grid(
            today.strftime("%B %Y"), num_days, grid_rows(entries, today.year, today.month)
        )

        text = _change_text(add, remove_request_id)
        url = _sheet_url()
        if url:
            text += f"  📋 <{url}|Leave sheet>"
        client.chat_postMessage(channel=channel, text=text)

        _save_board(db, channel, month, entries)
    except Exception:
        logger.exception("leave board update failed")
