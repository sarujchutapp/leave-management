# 1a: Book button (prefilled apply modal)

- Issue: #41
- Labels: ready-for-agent

---

## Parent

V4 PRD: #36

## What to build

A **Book button** on a suggested break that opens the existing leave apply modal
pre-filled with the break's start/end dates (Slack date pickers take an initial
date), so the caller submits it through the normal request flow without re-typing.

Booking reuses the current request path — no new write logic — and `validate_request`
still runs on submit as the safety net. Establishes the prefilled-modal mechanism
that the 1d "Book mine" slice reuses.

## Acceptance criteria

- [ ] Each suggested break has a Book button that opens the standard apply modal with the dates pre-filled.
- [ ] Submitting goes through the existing request flow (validation, manager ticket or auto-approve) unchanged.
- [ ] A break that has become invalid by submit time (e.g. balance changed) is caught by the existing validation, not silently booked.

## Blocked by

- 1a longest-break tracer: #37

---

## As-built (done)

- `/advance` now replies with Block Kit (was plain text): `build_advance_blocks`
  (in `leave/blocks.py`) renders a header + one section per suggested break, each
  with a **Book** button (`ADVANCE_BOOK_ACTION`) whose value is the break's
  `start|end` ISO dates. The no-break / unregistered replies stay plain text.
- `build_leave_modal` gains a `prefill` param (`{"leave_type","start","end"}`):
  sets the date pickers' `initial_date` and the leave-type `initial_option`
  (vacation). Backward compatible — `/dayoff` calls it without prefill.
- `open_book_modal` (handler) reads `start|end` from the button value and opens
  the prefilled apply modal via `views_open`. No new write path: submitting goes
  through the existing `submit_leave` → `validate_request` flow, which is the
  safety net for a break gone stale (balance changed) by submit time.
- `app.py`: registered `@app.action(ADVANCE_BOOK_ACTION)` synchronously (needs
  the trigger_id within 3s, like other modal opens).
- Tests (`tests/test_advance.py`): a Book button per option carrying its dates;
  the button opens the apply modal pre-filled with the right dates + vacation;
  existing option-rendering tests updated to read the blocks reply.

Establishes the prefilled-modal mechanism the 1d "Book mine" slice (#43) reuses.
The submit safety net itself is covered by the existing validation tests.
