"""Delete calendar events that are NOT tracked by the leave_requests table.

The Team Leave calendar may hold events from an older system (e.g. the previous
Postgres/Supabase setup) or stale tests, whose request rows no longer exist in
DynamoDB. Those are "orphaned". This deletes the orphaned events while KEEPING the
events still linked to a current leave_requests row (via calendar_event_id) — so the
DynamoDB-managed requests and their calendar entries stay in sync.

    python clear_calendar.py            # dry run: show KEEP (tracked) vs DELETE (orphaned)
    python clear_calendar.py --delete   # delete the orphaned ones only

Needs DynamoDB read (run as yourself, not the deploy role) + the Google service
account. From the repo root, venv active:

    source .venv/bin/activate
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
    python clear_calendar.py
"""

import sys

from dotenv import load_dotenv

load_dotenv()  # GOOGLE_SERVICE_ACCOUNT_FILE + TEAM_CALENDAR_ID

import boto3

from leave.calendar_client import CalendarClient

REGION = "ap-southeast-1"
REQUESTS_TABLE = "leave_requests"


def main():
    delete = "--delete" in sys.argv
    cal = CalendarClient.from_env()

    # Event IDs the current DynamoDB data tracks — these we KEEP.
    table = boto3.resource("dynamodb", region_name=REGION).Table(REQUESTS_TABLE)
    resp = table.scan(ProjectionExpression="calendar_event_id")
    rows = resp["Items"]
    while "LastEvaluatedKey" in resp:
        resp = table.scan(
            ProjectionExpression="calendar_event_id", ExclusiveStartKey=resp["LastEvaluatedKey"]
        )
        rows += resp["Items"]
    tracked_ids = {r["calendar_event_id"] for r in rows if r.get("calendar_event_id")}

    # Every event currently on the calendar.
    events, page_token = [], None
    while True:
        r = (
            cal.service.events()
            .list(calendarId=cal.calendar_id, singleEvents=True, maxResults=2500, pageToken=page_token)
            .execute()
        )
        events += r.get("items", [])
        page_token = r.get("nextPageToken")
        if not page_token:
            break

    orphaned = [e for e in events if e["id"] not in tracked_ids]
    kept = [e for e in events if e["id"] in tracked_ids]

    def show(label, evs):
        print(f"\n{label} ({len(evs)}):")
        for e in evs:
            start = e.get("start", {}).get("date") or e.get("start", {}).get("dateTime", "?")
            print(f"  {start}  {e.get('summary', '(no title)')}")

    show("KEEP — tracked by DynamoDB", kept)
    show("DELETE — orphaned (no DynamoDB row)", orphaned)

    if not delete:
        print("\nDry run — re-run with --delete to remove the orphaned events.")
        return

    for e in orphaned:
        cal.service.events().delete(calendarId=cal.calendar_id, eventId=e["id"]).execute()
    print(f"\nDeleted {len(orphaned)} orphaned events; kept {len(kept)}.")


if __name__ == "__main__":
    main()
