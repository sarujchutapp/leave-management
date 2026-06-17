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

import boto3

from datetime import date

from leave import db
from leave.board import reset_board
from leave.calendar_client import CalendarClient
from leave.sheets_client import SheetsClient

# The deployed region (resources live in ap-southeast-1; the state bucket is elsewhere).
REGION = "ap-southeast-1"
REQUESTS_TABLE = "leave_requests"
os.environ.setdefault("AWS_REGION", REGION)  # so db.connect() targets the right region


def main():
    calendar = CalendarClient.from_env()
    table = boto3.resource("dynamodb", region_name=REGION).Table(REQUESTS_TABLE)

    # Page through every request row.
    resp = table.scan()
    items = resp["Items"]
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items += resp["Items"]

    # Delete the calendar event each approved request created (skip ones already gone).
    events = 0
    for it in items:
        event_id = it.get("calendar_event_id")
        if event_id:
            try:
                calendar.delete_event(event_id)
                events += 1
            except Exception as e:
                print(f"  calendar event {event_id} skipped: {e}")

    # Wipe the request rows.
    with table.batch_writer() as bw:
        for it in items:
            bw.delete_item(Key={"request_id": it["request_id"]})

    # Reset the board: drop the saved state and blank the sheet (if configured).
    sheets = SheetsClient.from_env() if os.environ.get("LEAVE_SHEET_ID") else None
    reset_board(db.connect(), sheets, date.today())

    print(
        f"Deleted {len(items)} requests and {events} calendar events; reset the board"
        f"{' + sheet' if sheets else ''}."
    )


if __name__ == "__main__":
    main()
