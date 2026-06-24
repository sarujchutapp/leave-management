# 1d: Book mine (requester's slice)

- Issue: #43
- Labels: ready-for-agent

---

## Parent

V4 PRD: #36

## What to build

A **Book mine** button on the group-break result that books *only the requester's
own slice* of the shared window, via the prefilled apply modal mechanism, while
leaving each teammate to book their own.

Reuses the prefilled-modal path from the 1a Book button. No leave is ever booked on
behalf of another person. (A multi-party invitation/accept flow is explicitly a
future v2 — out of scope here.)

## Acceptance criteria

- [ ] The group-break result has a "Book mine" button that opens the apply modal pre-filled with the shared window dates for the requester only.
- [ ] Submitting goes through the existing request flow unchanged; no other member's leave is created or modified.
- [ ] The shareable text remains available so teammates can coordinate and book themselves.

## Blocked by

- 1a Book button: #41
- 1d group-break finder: #42

---

## As-built (done)

- The group-break result is now DM'd as Block Kit (was plain text):
  `build_group_result_blocks(window, text)` (in `leave/blocks.py`) renders the
  shareable line as a section plus a **Book mine** button. The button reuses the
  1a `ADVANCE_BOOK_ACTION` with value `start|end`, so clicking it routes to the
  existing `open_book_modal` → opens the apply modal pre-filled with the shared
  window's dates for the requester only. No new action or app.py wiring.
- `submit_group_break_apply`: when a window exists, `chat_postMessage(text=...,
  blocks=...)` — text keeps the copy-pasteable shareable line so teammates can
  coordinate and book themselves; the infeasible case still DMs `GROUP_NO_WINDOW`
  plain text. `_render_group_result` simplified to format a (non-None) window.
- No leave is booked on behalf of anyone: the button only opens the caller's own
  prefilled modal, and submitting goes through the unchanged `submit_leave` flow
  (validate_request as the safety net) which creates only the caller's request.

Tests (`tests/test_advance.py`): the result carries a "Book mine" button using
ADVANCE_BOOK_ACTION whose value is the shared window dates, and the shareable
text remains in the message. The prefilled-modal open itself is the 1a mechanism,
already covered by `test_book_button_opens_prefilled_apply_modal`.

Completes the V4 Leave Optimizer epic (#37, #40, #41 + #42, #43).
