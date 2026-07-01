"""Leave reports rendered to CSV text.

Pure `db -> CSV text` functions (no Slack), so they're tested directly:
- build_report_csv: all-employee quota (one row per employee x leave type),
  via a Scan on the employees table (reserved policy/board items skipped).
- build_history_csv: one person's full request history, via a single
  by_employee GSI query (cheaper than the all-employee scan).
"""

import csv
import io
from collections import namedtuple
from datetime import date

from boto3.dynamodb.conditions import Key

from leave.balance import request_days
from leave.blocks import LEAVE_TYPES
from leave.board import BOARD_KEY
from leave.burnout import expiring_quota, longest_working_stretch, no_break_stretch
from leave.db import get_employee
from leave.holidays import HOLIDAYS_KEY, holidays_between, holidays_for_year
from leave.policy import POLICY_KEY, get_policy
from leave.requests import (
    approved_weekdays_by_type_this_year,
    carry_in_for,
    remaining_balance,
    remaining_balances,
)

RESERVED = {POLICY_KEY, BOARD_KEY, HOLIDAYS_KEY}
HEADER = ["employee", "leave type", "used", "remaining", "carry-in"]
HISTORY_HEADER = [
    "employee",
    "leave type",
    "start",
    "end",
    "half",
    "status",
    "working days",
    "reason",
    "decline reason",
]
BURNOUT_HEADER = [
    "employee",
    "no-break stretch (days)",
    "remaining vacation",
    "days left in year",
    "longest working stretch (days)",
]


def _all_employees(db):
    items, scan_kwargs = [], {}
    while True:
        resp = db.employees.scan(**scan_kwargs)
        items += [i for i in resp["Items"] if i["slack_user_id"] not in RESERVED]
        if "LastEvaluatedKey" not in resp:
            return items
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def build_report_csv(db, today):
    """CSV text: one row per employee x leave type. `used`/`remaining` are the
    derived balances; `carry-in` is the vacation carry (0 for non-carrying types)."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(HEADER)
    for emp in sorted(_all_employees(db), key=lambda e: e.get("real_name", "")):
        balances = remaining_balances(db, emp, today)
        used = approved_weekdays_by_type_this_year(db, emp["slack_user_id"], today)
        carry = carry_in_for(db, emp, today)
        for leave_type in LEAVE_TYPES:
            if leave_type not in balances:
                continue
            writer.writerow(
                [
                    emp.get("real_name", ""),
                    leave_type,
                    used.get(leave_type, 0),
                    balances[leave_type],
                    carry if leave_type == "vacation" else 0,
                ]
            )
    return out.getvalue()


# One employee's burnout signals. Shared by the burnout CSV report and the
# /burnout board so the two can't drift. The board shows `stretch` + `remaining` +
# `next_break`; `days_left`/`working` are CSV-only columns; `expiring` rides the
# Nudge DM. `next_break` (the date of their next booked break, or None) both shows
# on the board and breaks ranking ties — relief lowers risk. `user_id` lets the
# board's Nudge button + avatar target the person.
BurnoutSignals = namedtuple(
    "BurnoutSignals",
    ["user_id", "name", "stretch", "remaining", "days_left", "working", "expiring", "next_break"],
)


def employee_burnout_signals(db, emp, today, holidays, year_start, days_left, max_carry_over):
    """One employee's burnout signals: the no-break stretch (rank key) plus the
    supporting flags. The stretch is days since their last *taken* leave up to today
    (backward only), and reads 0 while they are currently on approved leave — they're
    resting now, not enduring a run. `next_break` is the start of their earliest future
    approved/pending break (or None) — relief that lowers their risk on the board.
    Approved/pending leave are the breaks that reset the longest working stretch, which
    is measured over the elapsed year (year start .. today) — future days aren't worked
    yet. `expiring` is the vacation that won't carry past year-end under the live policy
    cap."""
    requests = _employee_requests(db, emp["slack_user_id"])
    taken_ends = [
        date.fromisoformat(r["end_date"])
        for r in requests
        if r["status"] == "approved" and date.fromisoformat(r["end_date"]) < today
    ]
    on_leave_today = any(
        date.fromisoformat(r["start_date"]) <= today <= date.fromisoformat(r["end_date"])
        for r in requests
        if r["status"] == "approved"
    )
    booked_starts = [
        date.fromisoformat(r["start_date"])
        for r in requests
        if r["status"] in ("approved", "pending") and date.fromisoformat(r["start_date"]) > today
    ]
    leave_ranges = [
        (date.fromisoformat(r["start_date"]), date.fromisoformat(r["end_date"]))
        for r in requests
        if r["status"] in ("approved", "pending")
    ]
    stretch = 0 if on_leave_today else no_break_stretch(today, max(taken_ends, default=None))
    working = longest_working_stretch(year_start, today, leave_ranges, holidays)
    remaining = remaining_balance(db, emp, "vacation", today)
    expiring = expiring_quota(remaining, max_carry_over)
    next_break = min(booked_starts, default=None)
    return BurnoutSignals(
        emp["slack_user_id"], emp.get("real_name", ""), stretch, remaining, days_left, working, expiring, next_break
    )


def ranked_burnout_signals(db, employees, today):
    """Each employee's burnout signals, ranked most at risk first: longest no-break
    stretch first, then — among equal stretches — whoever has *nothing* booked ahead
    (no relief coming) ranks higher, then name. The single computation the burnout
    CSV report and the /burnout board both call, so they cannot drift. Reads the
    live policy carry-over cap once for the expiring figure."""
    year_start = date(today.year, 1, 1)
    year_end = date(today.year, 12, 31)
    holidays = holidays_for_year(db, today.year)
    days_left = (year_end - today).days
    max_carry_over = get_policy(db)["max_carry_over"]["vacation"]
    signals = [
        employee_burnout_signals(db, emp, today, holidays, year_start, days_left, max_carry_over)
        for emp in employees
    ]
    signals.sort(key=lambda s: (-s.stretch, s.next_break is not None, s.name))
    return signals


def build_burnout_csv(db, today):
    """CSV text: one row per employee, ranked by no-break stretch (longest first,
    name as tie-break). Each row carries the supporting flags — remaining vacation
    vs days left in the year, and the longest working stretch — so the admin can
    see why a person ranks where they do. db -> CSV, like the other reports."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(BURNOUT_HEADER)
    for s in ranked_burnout_signals(db, _all_employees(db), today):
        writer.writerow([s.name, s.stretch, s.remaining, s.days_left, s.working])
    return out.getvalue()


def _employee_requests(db, employee_id):
    items, query_kwargs = [], {}
    while True:
        resp = db.requests.query(
            IndexName=db.by_employee_index,
            KeyConditionExpression=Key("employee_id").eq(employee_id),
            **query_kwargs,
        )
        items += resp["Items"]
        if "LastEvaluatedKey" not in resp:
            return items
        query_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def build_history_csv(db, employee_id):
    """CSV text: one row per request for this employee (all statuses, all time),
    oldest first. `working days` is the quota each request consumes (weekday count,
    holidays excluded; 0.5 for a half-day)."""
    employee = get_employee(db, employee_id)
    name = (employee or {}).get("real_name", employee_id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(HISTORY_HEADER)
    rows = sorted(_employee_requests(db, employee_id), key=lambda r: r.get("start_date", ""))
    for r in rows:
        start = date.fromisoformat(r["start_date"])
        end = date.fromisoformat(r["end_date"])
        days = request_days(start, end, r.get("half"), holidays_between(db, start, end))
        writer.writerow(
            [
                name,
                r["leave_type"],
                r["start_date"],
                r["end_date"],
                r.get("half") or "",
                r["status"],
                days,
                r.get("reason") or "",
                r.get("decline_reason") or "",
            ]
        )
    return out.getvalue()
