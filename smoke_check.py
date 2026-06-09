"""Verify the three external integrations are configured correctly.

Run after filling in .env:  python smoke_check.py
Each check runs independently and reports pass/fail; a failure in one does not stop the others.
"""

import datetime
import os

from dotenv import load_dotenv

load_dotenv()

results = []


def record(name, fn):
    try:
        detail = fn()
        results.append((name, True, detail))
    except Exception as e:
        results.append((name, False, f"{type(e).__name__}: {e}"))


def check_slack():
    from slack_sdk import WebClient
    from slack_sdk.socket_mode import SocketModeClient

    web = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
    auth = web.auth_test()  # validates bot token

    app_token = os.environ["SLACK_APP_TOKEN"]
    if not app_token.startswith("xapp-"):
        raise ValueError("SLACK_APP_TOKEN should start with 'xapp-'")
    smc = SocketModeClient(app_token=app_token, web_client=web)
    smc.connect()  # validates app-level token by opening a Socket Mode connection
    smc.disconnect()
    smc.close()

    return f"bot @{auth['user']} in workspace '{auth['team']}', Socket Mode connected"


def check_dynamodb():
    from leave import db

    handle = db.connect()
    client = handle.employees.meta.client
    emp = client.describe_table(TableName=db.EMPLOYEES_TABLE)["Table"]["TableStatus"]
    req = client.describe_table(TableName=db.REQUESTS_TABLE)["Table"]["TableStatus"]
    return f"connected; {db.EMPLOYEES_TABLE}={emp}, {db.REQUESTS_TABLE}={req}"


def check_calendar():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"],
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    service = build("calendar", "v3", credentials=creds)
    cal_id = os.environ["TEAM_CALENDAR_ID"]

    start = datetime.date.today() + datetime.timedelta(days=1)
    end = start + datetime.timedelta(days=1)
    body = {
        "summary": "Leave bot smoke check (safe to delete)",
        "start": {"date": start.isoformat()},
        "end": {"date": end.isoformat()},
    }
    created = service.events().insert(calendarId=cal_id, body=body).execute()
    service.events().get(calendarId=cal_id, eventId=created["id"]).execute()
    service.events().delete(calendarId=cal_id, eventId=created["id"]).execute()
    return "service account can insert, read, and delete events"


record("Slack", check_slack)
record("DynamoDB", check_dynamodb)
record("Google Calendar", check_calendar)

print()
all_ok = True
for name, ok, detail in results:
    mark = "PASS" if ok else "FAIL"
    if not ok:
        all_ok = False
    print(f"[{mark}] {name}: {detail}")
print()

raise SystemExit(0 if all_ok else 1)
