"""Clear all leave requests and their Google Calendar events — a clean slate.

Empties the `leave_requests` DynamoDB table, deletes the calendar events those
approvals created (via each row's `calendar_event_id`), and resets the leave board
(drops the saved board state and blanks the sheet). Leaves `leave_employees`
intact, so the bot still recognizes everyone (the reserved central-policy item is
also kept; only the `__board__` item is removed).

Run as YOURSELF (not the deploy role — it has no item-level DynamoDB permission),
from the repo root, with the venv active:

    source .venv/bin/activate
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
    python clear_requests.py

Needs `service-account.json` + `TEAM_CALENDAR_ID` (read from `.env`) for the calendar
deletes; set `LEAVE_SHEET_ID` too to blank the board sheet. Does NOT touch Slack
messages, manually-created calendar events, or stored carry_in (use recompute_carry.py).
"""

import os

from dotenv import load_dotenv

load_dotenv()  # GOOGLE_SERVICE_ACCOUNT_FILE + TEAM_CALENDAR_ID + LEAVE_SHEET_ID

from datetime import date

from leave import db
from leave.calendar_client import CalendarClient
from leave.requests import clear_all_requests
from leave.sheets_client import SheetsClient

# The deployed region (resources live in ap-southeast-1; the state bucket is elsewhere).
REGION = "ap-southeast-1"
os.environ["AWS_REGION"] = REGION  # force: all bot resources live here, regardless of .env


def main():
    calendar = CalendarClient.from_env()
    sheets = SheetsClient.from_env() if os.environ.get("LEAVE_SHEET_ID") else None
    count = clear_all_requests(db.connect(), calendar, sheets, date.today())
    print(f"Deleted {count} requests; reset the board{' + sheet' if sheets else ''}.")


if __name__ == "__main__":
    main()
