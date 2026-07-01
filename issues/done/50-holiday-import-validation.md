# Holiday import: all-or-nothing validation with line-numbered errors

- **Tracker:** #50
- **Labels:** ready-for-agent

---

## Parent

PRD #48 — Import holidays from Slack (paste CSV): #48

## What to build

Add all-or-nothing validation to the holiday import paste (built in #49). When the pasted
text contains any invalid row — an unparseable date, or a row missing its label — the
submit returns an inline modal error that names the offending line(s) and imports
**nothing**: the holidays store and the Team Leave calendar are left unchanged. An empty
paste (or whitespace only) is likewise rejected with a clear inline message.

The admin fixes the flagged lines and re-pastes; a corrected paste then imports cleanly.
All-or-nothing keeps "what landed" unambiguous — the admin never has to guess which rows
made it in.

## Acceptance criteria

- [ ] A paste containing any row with an unparseable date returns an inline error and imports nothing.
- [ ] A paste containing any row missing a label returns an inline error and imports nothing.
- [ ] The error names the offending line(s) so the admin knows exactly what to fix.
- [ ] An empty paste (or whitespace only) is rejected with a clear inline message.
- [ ] When validation fails, the holidays store and the Team Leave calendar are unchanged.
- [ ] A subsequent corrected paste imports successfully.
- [ ] Tests cover the validation paths at the pure parser seam (line-numbered errors, empty input) and the inline-error path at the handler seam (fake Slack client), following the prior art in `tests/test_control.py`.

## Blocked by

- #49 — Holiday import: Import mode — paste and apply (happy path)
