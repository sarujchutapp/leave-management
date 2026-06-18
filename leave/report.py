"""All-employee leave usage/quota report rendered to CSV text.

A pure `db -> CSV text` function (no Slack), so it's tested directly. Iterates
every employee via a Scan on the employees table, skipping the reserved policy
and board items, and emits one row per employee x leave type with the same
figures `/dayoff` shows: used this year and remaining balance, plus the
vacation carry-in.
"""

import csv
import io

from leave.blocks import LEAVE_TYPES
from leave.board import BOARD_KEY
from leave.policy import POLICY_KEY
from leave.requests import (
    approved_weekdays_by_type_this_year,
    carry_in_for,
    remaining_balances,
)

RESERVED = {POLICY_KEY, BOARD_KEY}
HEADER = ["employee", "leave type", "used", "remaining", "carry-in"]


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
