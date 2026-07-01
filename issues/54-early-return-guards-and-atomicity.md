# Early return: guards (zero-reclaim, half-day) and atomic write

- **Tracker:** #54
- **Labels:** ready-for-agent

---

## Parent

PRD #52 — Early return: cancel an in-progress leave: #52

## What to build

Guard the early-return path built in #53 against the cases where there's nothing to
return, and make the write safe under a race.

- **Zero-reclaim:** an in-progress leave with no working days after today is not offered
  as an early return — a leave that ends today, or one whose remaining days are all
  weekend/holiday. There's nothing to give back, so it shouldn't appear as a
  return-early option.
- **Half-day:** a half-day (always a single date) is never an early return.
- **Atomicity:** the early-return write shortens the end date under a conditional guard
  that the request is still approved (the same approach as the approve/decline/cancel
  transitions), so a racing cancel or a double-submit can't apply the change twice or
  double-fire its side effects.

## Acceptance criteria

- [ ] An in-progress leave that ends today is not offered as an early return.
- [ ] An in-progress leave whose remaining days (after today) are all weekend/holiday is not offered as an early return.
- [ ] A half-day is never offered as an early return.
- [ ] The early-return write applies only when the request is still approved; a second racing attempt reports it did not apply and fires no duplicate side effects.
- [ ] Tests cover each guard at the `requests.py` seam (zero-reclaim classification, the conditional write returning whether it applied) and the handler seam, following the prior art in `tests/test_cancel.py` and the atomic-transition tests in `tests/test_approval.py`.

## Blocked by

- #53 — Early return: end an in-progress leave (happy path)
