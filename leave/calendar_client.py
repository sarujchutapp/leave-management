"""Thin wrapper over the Google Calendar API for the shared Team Leave calendar.

Injected into handlers so tests can substitute a fake.
"""

import hashlib
import os
from datetime import timedelta

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Google Calendar's 11 named event colours ("1".."11"). Each person is mapped to one
# so the shared calendar is readable at a glance (collisions possible beyond 11 people).
CALENDAR_COLOR_IDS = [str(i) for i in range(1, 12)]


def color_id_for(key):
    """Stable Google Calendar colorId for an employee key (e.g. slack_user_id).
    Uses a fixed hash so the colour is consistent across events and processes."""
    h = int(hashlib.sha1(key.encode()).hexdigest(), 16)
    return CALENDAR_COLOR_IDS[h % len(CALENDAR_COLOR_IDS)]


class CalendarClient:
    def __init__(self, service, calendar_id):
        self.service = service
        self.calendar_id = calendar_id

    @classmethod
    def from_env(cls):
        # Imported here, not at module load, so cold-start paths that never build a
        # calendar client — e.g. opening the /dayoff modal — don't pay for the heavy
        # google-api-python-client import (it dominated cold-start Init Duration).
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"], scopes=SCOPES
        )
        service = build("calendar", "v3", credentials=creds)
        return cls(service, os.environ["TEAM_CALENDAR_ID"])

    def create_event(self, summary, start, end, color_id=None):
        """All-day event over the inclusive range. Google's all-day end date is
        exclusive, so add a day. `color_id` (a Google colorId) tints the event.
        Returns the created event id."""
        body = {
            "summary": summary,
            "start": {"date": start.isoformat()},
            "end": {"date": (end + timedelta(days=1)).isoformat()},
        }
        if color_id:
            body["colorId"] = color_id
        created = self.service.events().insert(calendarId=self.calendar_id, body=body).execute()
        return created["id"]

    def update_event(self, event_id, summary):
        """Patch an existing event's summary (used when a holiday's label changes)."""
        self.service.events().patch(
            calendarId=self.calendar_id, eventId=event_id, body={"summary": summary}
        ).execute()

    def delete_event(self, event_id):
        self.service.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()
