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

---

## As-built (done)

- Pure core `leave/optimizer.py`: `longest_break(today, year_end, balance, holidays,
  existing_ranges, cap) -> LeaveBreak | None`. Brute-forces booking ranges
  `[b_start, b_end]` (working-day endpoints, length bounded by `cap`), counts quota as
  working days, and measures the resulting continuous absence with the same
  weekend/holiday/existing-leave accounting as `continuous_absence_length`. Rejects
  spans over `cap` and bookings that overlap existing leave; `b_end <= year_end` keeps
  every booked working day in this year (the span may still spill into January via free
  days). Ranks longest span → least quota → earliest.
- Gather + render in `leave/handlers.py` (`_suggest_longest_break`, `_render_break`,
  `open_advance`), reusing `remaining_balance`, `holidays_for_year`,
  `active_full_leave_ranges`, and the policy consecutive limit — so a suggestion always
  passes `validate_request` (asserted in `test_advance.py`).
- `/advance` wired in `app.py` synchronously (read-only, text reply, no modal).
- Tests: `tests/test_optimizer.py` (bridge selection, cap bound, building around
  bookings, year boundary, tie-break, no-balance) and `tests/test_advance.py` (seam:
  unregistered, has-balance, top-of-chain, no-balance, validation round-trip).

Next slices: #40 (top 2–3 distinct options), #41 (Book button / prefilled modal),
#42 (group-break finder) all build on this `optimizer.py` + `/advance` foundation.
