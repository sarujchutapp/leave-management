# 1a: /advance longest-break tracer (single best break)

- Issue: #37
- Labels: ready-for-agent

---

## Parent

V4 PRD: #36

## What to build

The first tracer through the **Leave Optimizer**: a new employee command `/advance`
that computes and shows the single longest **continuous absence** the caller can
still take in the current calendar year, and replies with it as text.

End-to-end: introduce the pure `leave/optimizer.py` module (math over plain inputs —
remaining vacation balance, holiday set, existing full-day leave ranges, the live
consecutive limit, horizon today→Dec 31), a thin gather layer that sources those
inputs from the db (reusing `remaining_balance`, `holidays_for_year`,
`active_full_leave_ranges`, and the policy's consecutive limit), and the `/advance`
command handler that renders the result.

Scope of this slice: **one** best break only (longest; tie-break least quota, then
earliest). Vacation-only, full-day. Existing pending/approved leave, weekends, and
holidays fill runs (reuse the `continuous_absence_length` accounting), so the break
may extend an existing booking. The break stays within the live consecutive limit so
it is always bookable, and only spends this-year working days (it may spill into
January via free days, never via a January working day). No Book button and no
multi-option list yet (later slices).

## Acceptance criteria

- [ ] `/advance` responds with the longest single break the caller can still take this year: the dates to book, the vacation-day cost, and the resulting days-off span.
- [ ] The suggested break never exceeds the live consecutive limit, so it would pass `validate_request`.
- [ ] The break builds around the caller's existing pending/approved leave, weekends, and holidays (may extend an existing booking).
- [ ] The break never spends a working day in the next calendar year.
- [ ] A caller with no remaining vacation (or no bookable break) gets a clear "nothing to suggest" reply rather than an error.
- [ ] A top-of-chain caller (no manager) can run `/advance` and get a result.
- [ ] The optimizer core is a pure function tested directly with hand-built inputs (balance, holiday set, existing ranges, cap), covering bridge selection, the cap bound, building around bookings, and the year boundary.

## Blocked by

None - can start immediately.
