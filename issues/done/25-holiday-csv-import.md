# Holiday CSV import + calendar mirror

- Tracker: #25
- Labels: AFK, ready-for-agent

## Parent

#21 — PRD: Leave Management V2

## What to build

Let an admin maintain holidays as a CSV (date + label) and apply it with an operator script (same pattern as `add_employees.py`). Applying the CSV does two things from one source: it upserts the `holidays` store (the source of truth for quota math) and mirrors each holiday onto the shared **Team Leave calendar** as an all-day event with a clear title prefix (e.g. "Holiday: Songkran").

End-to-end behavior:
- An import script parses the CSV rows and upserts holidays by date.
- For each holiday, an all-day calendar event is created and its `calendar_event_id` stored on the holiday row.
- Re-import is **idempotent**: editing the CSV and re-applying updates existing holidays/events rather than duplicating them.
- **Add/update-only**: removing a date from the CSV does not delete the holiday or its event (manual fix; full desired-state sync is out of scope).

## Acceptance criteria

- [ ] An operator script imports a CSV of (date, label) into the `holidays` store.
- [ ] Each imported holiday is mirrored as an all-day event on the Team Leave calendar with a recognizable title; the event id is stored on the holiday row.
- [ ] Re-importing an edited CSV updates existing rows/events and does not create duplicate calendar events.
- [ ] Removing a date from the CSV leaves the existing holiday/event intact (add/update-only).
- [ ] The thin CSV file-reader stays an operator script; the parse-and-apply function is tested over the moto `db` fixture with FakeCalendar, asserting upserted rows and mirrored events (including idempotent re-import).

## Blocked by

- #24 (Holiday-aware day-counting + holidays store) — needs the holidays store.

## Done (2026-06-16)

Implemented via TDD; all acceptance criteria met. Full suite 75 passed, no regressions.

- [x] Operator script (`import_holidays.py`) imports a CSV of (date, label) into the holidays store.
- [x] Each holiday is mirrored as an all-day Team Leave calendar event titled "Holiday: <label>"; the event id is stored on the holiday row.
- [x] Re-importing an edited CSV updates the existing row/event (label change patches the event) and creates no duplicate event.
- [x] Add/update-only: a date absent from a later import is left intact.
- [x] The thin CSV file-reader stays an operator script; `apply_holidays` + `parse_holiday_rows` are tested over the moto `db` fixture with FakeCalendar (create, idempotent re-import, add/update-only, parsing).

**Key decisions / deviations:**
- **Code/data split.** Unlike `add_employees.py` (which embeds the data and is gitignored), the holiday script is generic and reads a CSV path, so `import_holidays.py` + `holidays.example.csv` are committed and only the real `holidays.csv` is gitignored.
- **Idempotency via lookup, not delete+recreate.** `apply_holidays` checks `get_holiday` first: existing row with an event → `calendar.update_event` (patch summary); new → `create_event`. Added `CalendarClient.update_event` (events().patch) + `FakeCalendar.update_event`.
- **Title prefix** "Holiday: <label>" so closures read clearly next to leave on the shared calendar.

**Notes:** No Terraform/IAM change in this slice — the import runs as the human operator (full DynamoDB + Calendar access), per ADR-0003; the Lambda only reads holidays (granted in #24). #27 (consecutive limit) is the last holiday-dependent consumer; #26 (carry-over) and #28 (leave board) remain.
