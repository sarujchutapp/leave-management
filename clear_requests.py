"""Clear all leave requests and their Google Calendar events — a clean slate.

Empties the `leave_requests` DynamoDB table and deletes the calendar events those
approvals created (via each row's `calendar_event_id`). Leaves `leave_employees`
intact, so the bot still recognizes everyone.

Run as YOURSELF (not the deploy role — it has no item-level DynamoDB permission),
from the repo root, with the venv active:

    source .venv/bin/activate
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
    python clear_requests.py

Needs `service-account.json` + `TEAM_CALENDAR_ID` (read from `.env`) for the
calendar deletes. Does NOT touch Slack messages or manually-created calendar events.
"""

from dotenv import load_dotenv

load_dotenv()  # GOOGLE_SERVICE_ACCOUNT_FILE + TEAM_CALENDAR_ID for the calendar client

import boto3

from leave.calendar_client import CalendarClient

# The deployed region (resources live in ap-southeast-1; the state bucket is elsewhere).
REGION = "ap-southeast-1"
REQUESTS_TABLE = "leave_requests"


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

    print(f"Deleted {len(items)} requests and {events} calendar events.")


if __name__ == "__main__":
    main()
