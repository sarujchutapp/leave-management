# Holiday Remove picker: scope to today-onward (stay under Slack's 100-option limit)

- **Tracker:** #51
- **Labels:** ready-for-agent

---

## Parent

PRD #48 — Import holidays from Slack (paste CSV): #48

## What to build

Scope the `/control → Holidays` **Remove** mode dropdown to holidays dated **today or
later**. Holidays are stored as concrete dated entries (~21 per year) and accumulate
year over year without pruning, so the remove picker grows unbounded and would cross
Slack's hard 100-options-per-`static_select` limit after roughly five years — at which
point the modal fails to open. Filtering the picker to current-and-future dates keeps it
at the natural ~21–42 options **permanently**, so it can never hit the ceiling, while
still showing each option as `date — label`.

A remove picker exists to fix upcoming holidays; a past holiday never affects future
leave counting, and a re-import can overwrite anything, so dropping past dates from the
picker costs nothing.

This is a one-line scope filter on the options the Remove mode renders — no cascade, no
extra step, no new action handler.

## Acceptance criteria

- [ ] The Remove mode dropdown lists only holidays dated today or later.
- [ ] Holidays dated before today are excluded from the picker.
- [ ] A far-future accumulation of holidays across many years keeps the picker under the 100-option limit, so the modal still opens.
- [ ] Each option still shows its `date — label` text.
- [ ] Removing a listed holiday still deletes the store entry and its calendar event (unchanged behavior).
- [ ] With no current-or-future holidays, the Remove mode shows the existing empty-state note rather than an empty dropdown.
- [ ] Tests cover the today-onward scoping at the handler/modal seam, following the prior art in `tests/test_control.py` (the existing Remove-mode tests).

## Blocked by

None - can start immediately
