"""Import company holidays from a CSV into the leave_holidays table and mirror
them onto the shared Team Leave calendar. Run as yourself (not the deploy role):

    source .venv/bin/activate
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
    python import_holidays.py holidays.csv

CSV format (an optional `date,label` header is skipped):

    2026-04-13,Songkran
    2026-12-31,New Year's Eve

Re-running is safe and idempotent: it updates existing holidays/events and never
creates duplicates. It is add/update-only — to remove a holiday, delete its row
and calendar event manually.
"""

import csv
import os
import sys

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("AWS_REGION", "ap-southeast-1")  # the region the bot's tables live in

from leave import db
from leave.calendar_client import CalendarClient
from leave.holidays import apply_holidays, parse_holiday_rows


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "holidays.csv"
    with open(path, newline="") as f:
        rows = parse_holiday_rows(list(csv.reader(f)))
    apply_holidays(db.connect(), CalendarClient.from_env(), rows)
    print(f"Applied {len(rows)} holidays from {path}.")


if __name__ == "__main__":
    main()
