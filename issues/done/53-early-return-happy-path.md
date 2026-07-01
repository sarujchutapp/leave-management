# Early return: end an in-progress leave (happy path)

- **Tracker:** #53
- **Labels:** ready-for-agent

---

## Parent

PRD #52 — Early return: cancel an in-progress leave: #52

## What to build

In-progress approved leaves (start ≤ today ≤ end) now appear in the `/dayoff-cancel`
picker, marked with a plain-text `(in progress)` label. Cancelling one is an **early
return**: the leave is shortened to end **today** — the days already taken through today
stay taken (still approved, still consumed, still on the record), and only the working
days *after* today are returned to the employee's balance and cleared from the Team
calendar and the leave board. It applies immediately (no approval). A distinct manager
(not a self-approving top-of-chain employee) is FYI'd that the report returned early and
how the leave changed. The employee gets a result DM explaining it ended early, kept
through today, and how many days came back.

Cancelling a pending or not-yet-started approved leave still fully cancels it, exactly as
today — the flow branches on whether the picked leave is in progress.

Because balance is derived from approved weekdays, shortening the end date refunds the
tail automatically (no stored-balance write, no carry-in recompute). The calendar event
is re-dated by deleting the old one and creating a new one for `[start, today]` (the
calendar client can only patch a title), storing the new id. The board entry is updated
to the new end so the returned days clear from the grid.

## Acceptance criteria

- [ ] In-progress approved leaves appear in the `/dayoff-cancel` picker, marked `(in progress)`.
- [ ] Cancelling an in-progress leave shortens it to end today; the request stays approved.
- [ ] Only working days after today are returned to the balance; days through today remain consumed.
- [ ] The returned days clear from the Team calendar (event re-dated to `[start, today]`) and the leave board.
- [ ] A distinct manager is FYI'd; a self-approving top-of-chain employee triggers no FYI.
- [ ] The employee's result DM states the leave ended early, kept through today, and how many days were returned.
- [ ] Cancelling a pending or not-yet-started approved leave still fully cancels and refunds it, unchanged.
- [ ] Carry-over stays correct with no manual recompute (reclaimed days flow through the derived balance).
- [ ] Tests at the `requests.py` seam (in-progress listing/classification, reclaim-days math, the early-return write) and the handler seam (`submit_cancel`/`open_cancel_modal` with fake calendar/Slack), plus the `(in progress)` marker at the `build_cancel_modal` seam — following the prior art in `tests/test_cancel.py`.

## Blocked by

None - can start immediately
