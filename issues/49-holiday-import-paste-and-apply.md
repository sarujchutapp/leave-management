# Holiday import: Import mode — paste and apply (happy path)

- **Tracker:** #49
- **Labels:** ready-for-agent

---

## Parent

PRD #48 — Import holidays from Slack (paste CSV): #48

## What to build

Add an **Import** mode to the `/control → Holidays` modal, alongside the existing Add and
Remove modes, switched via the same mode select (in-place re-render). Import mode shows a
single multiline text field into which the admin pastes their holiday list as
`date,label` rows.

On submit — admin-gated, running post-ack so the ack stays within Slack's 3s window — the
pasted text is parsed and applied through the existing add/update path: each row is
upserted into the holidays store and mirrored onto the Team Leave calendar (idempotently,
so a re-import updates an existing event rather than duplicating it). Parsing accepts
comma- or tab-delimited rows (Excel/Sheets copy yields tabs), splits each line on the
first delimiter only so a label keeps any commas it contains, and skips a leading
`date,label` header and blank lines. Merge semantics: an import adds or updates the pasted
dates and never deletes, so importing one year leaves other years untouched. The admin
gets a confirmation DM naming how many holidays were imported.

This slice is the happy path — it assumes valid input; row-level validation and error
surfacing are the next slice.

## Acceptance criteria

- [ ] The Holidays modal offers an Import mode alongside Add and Remove, reached via the existing mode select.
- [ ] Import mode shows a multiline text field for pasting `date,label` rows.
- [ ] A valid paste of comma-separated rows imports every holiday — stored and mirrored onto the Team Leave calendar.
- [ ] Tab-separated rows (a straight Excel/Sheets copy) import identically.
- [ ] A label containing a comma is preserved (parser splits on the first delimiter only).
- [ ] A leading `date,label` header row and blank lines are ignored.
- [ ] Re-importing an existing date with a new label updates it in place — no duplicate calendar event.
- [ ] Importing one year's holidays does not disturb another year's (merge / add-update only).
- [ ] Only an admin can import; a non-admin submit is rejected.
- [ ] The submit acks within Slack's 3s window; the parse + apply + calendar mirror run post-ack.
- [ ] The admin receives a confirmation naming how many holidays were imported.
- [ ] Tests cover the paste parser (comma and tab, comma-in-label, header/blank skip) at the pure seam and the import at the handler seam (fake Slack client), following the prior art in `tests/test_holiday_import.py` and the holiday tests in `tests/test_control.py`.

## Blocked by

None - can start immediately
