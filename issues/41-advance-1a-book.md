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
