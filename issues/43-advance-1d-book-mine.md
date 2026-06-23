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
