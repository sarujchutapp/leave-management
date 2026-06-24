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
from leave.burnout import longest_working_stretch, no_break_stretch
from leave.db import get_employee
from leave.holidays import HOLIDAYS_KEY, holidays_between, holidays_for_year
from leave.policy import POLICY_KEY
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
        carry = carry_in_for(db, emp, today.year)
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


# One employee's burnout signals, in the order the BURNOUT_HEADER lists them.
# Shared by the burnout CSV report and the /burnout board so the two can't drift.
BurnoutSignals = namedtuple(
    "BurnoutSignals", ["name", "stretch", "remaining", "days_left", "working"]
)


def employee_burnout_signals(db, emp, today, holidays, year_start, year_end, days_left):
    """One employee's burnout signals: the no-break stretch (rank key) plus the
    supporting flags. Past *approved* leave that has ended anchors the stretch;
    the earliest future approved/pending leave closes it. Approved/pending leave
    are the breaks that reset the longest working stretch."""
    requests = _employee_requests(db, emp["slack_user_id"])
    taken_ends = [
        date.fromisoformat(r["end_date"])
        for r in requests
        if r["status"] == "approved" and date.fromisoformat(r["end_date"]) < today
    ]
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
    stretch = no_break_stretch(today, max(taken_ends, default=None), min(booked_starts, default=None))
    working = longest_working_stretch(year_start, year_end, leave_ranges, holidays)
    remaining = remaining_balance(db, emp, "vacation", today)
    return BurnoutSignals(emp.get("real_name", ""), stretch, remaining, days_left, working)


def ranked_burnout_signals(db, employees, today):
    """Each employee's burnout signals, ranked by no-break stretch (longest first,
    name as tie-break). The single computation the burnout CSV report and the
    /burnout board both call, so the signals they show cannot drift."""
    year_start = date(today.year, 1, 1)
    year_end = date(today.year, 12, 31)
    holidays = holidays_for_year(db, today.year)
    days_left = (year_end - today).days
    signals = [
        employee_burnout_signals(db, emp, today, holidays, year_start, year_end, days_left)
        for emp in employees
    ]
    signals.sort(key=lambda s: (-s.stretch, s.name))
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
