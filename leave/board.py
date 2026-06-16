"""The shared leave board: one live-updating Slack message rendering the current
month as a people x days grid, replacing the old Excel-photo-in-chat ritual.

Denormalized by design (see issue #28 / ADR-0001's no-scan stance): the month's
approved leave is kept as a reserved `__board__` item in the employees table
(channel, month, ts, entries) and updated incrementally from the approve/cancel
handlers — no cross-employee scan. The channel comes from LEAVE_BOARD_CHANNEL;
absent it, the board is disabled. Rendering is provisional text/Block Kit.
"""

import os
from calendar import monthrange
from datetime import date, timedelta

from leave.holidays import holidays_for_year

BOARD_KEY = "__board__"
GLYPH = {"full": "#", "morning": "\\", "afternoon": "/"}
LEGEND = "`#` full · `\\` morning · `/` afternoon · `*` holiday"


def get_board(db):
    return db.employees.get_item(Key={"slack_user_id": BOARD_KEY}).get("Item")


def _save_board(db, channel, month, ts, entries):
    db.employees.update_item(
        Key={"slack_user_id": BOARD_KEY},
        UpdateExpression="SET channel = :c, #m = :m, ts = :t, entries = :e",
        ExpressionAttributeNames={"#m": "month"},
        ExpressionAttributeValues={":c": channel, ":m": month, ":t": ts, ":e": entries},
    )


def build_board_blocks(month_label, num_days, rows, holiday_days):
    """Pure renderer: a monospace people x days grid. `rows` is
    [{name, cells: {day: glyph}}]; `holiday_days` is a set of day numbers."""
    days = range(1, num_days + 1)
    ruler = "".join(str(d % 10) for d in days)
    hol = "".join("*" if d in holiday_days else " " for d in days)
    lines = [f"{'':<4}{ruler}", f"{'HOL':<4}{hol}"]
    for r in rows:
        cells = "".join(r["cells"].get(d, ".") for d in days)
        lines.append(f"{r['name'][:3]:<4}{cells}")
    grid = "```\n" + "\n".join(lines) + "\n```"
    return [
        {"type": "header", "text": {"type": "plain_text", "text": f"Leave — {month_label}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": grid}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": LEGEND}]},
    ]


def _rows_from_entries(entries, year, month):
    first, last = date(year, month, 1), date(year, month, monthrange(year, month)[1])
    by_name = {}
    for e in entries.values():
        start, end = date.fromisoformat(e["start"]), date.fromisoformat(e["end"])
        if start > last or end < first:
            continue  # leave doesn't touch this month
        cells = by_name.setdefault(e["name"], {})
        if e.get("half"):
            cells[start.day] = GLYPH[e["half"]]
        else:
            d = max(start, first)
            while d <= min(end, last):
                cells[d.day] = GLYPH["full"]
                d += timedelta(days=1)
    return [{"name": n, "cells": c} for n, c in sorted(by_name.items())]


def update_board(db, client, today, *, add=None, remove_request_id=None):
    """Apply one change (an approved leave added, or a request removed) to the
    board and reflect it in Slack. Posts a fresh message when the month turns,
    otherwise edits the canonical message in place. No-op if no channel is set."""
    channel = os.environ.get("LEAVE_BOARD_CHANNEL")
    if not channel:
        return

    month = f"{today.year:04d}-{today.month:02d}"
    board = get_board(db)
    same_month = board is not None and board.get("month") == month
    entries = dict(board.get("entries") or {}) if same_month else {}

    if add:
        entries[add["request_id"]] = {
            "name": add["name"],
            "start": add["start"].isoformat(),
            "end": add["end"].isoformat(),
            "half": add.get("half"),
        }
    if remove_request_id:
        entries.pop(remove_request_id, None)

    num_days = monthrange(today.year, today.month)[1]
    holiday_days = {
        d.day for d in holidays_for_year(db, today.year) if d.month == today.month
    }
    rows = _rows_from_entries(entries, today.year, today.month)
    blocks = build_board_blocks(today.strftime("%B %Y"), num_days, rows, holiday_days)

    reuse = same_month and board.get("ts")
    if reuse:
        client.chat_update(channel=channel, ts=board["ts"], text="Leave board", blocks=blocks)
        ts = board["ts"]
    else:
        resp = client.chat_postMessage(channel=channel, text="Leave board", blocks=blocks)
        ts = resp["ts"]
    _save_board(db, channel, month, ts, entries)
