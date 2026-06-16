# Consecutive-absence limit

- Tracker: #27
- Labels: AFK, ready-for-agent

## Parent

#21 — PRD: Leave Management V2

## What to build

Cap how long an employee can be continuously away. A **continuous absence** is a maximal unbroken run of consecutive calendar days the employee does not work — filled by leave of **any** type, weekends, and holidays, bounded on each side by a day actually worked. A new **vacation** request is rejected if it would create a continuous absence longer than the company cap (15 calendar days initially, from central policy).

End-to-end behavior:
- A new check in request validation extends outward from the requested dates through adjacent weekends, holidays, and the employee's existing pending/approved leave, then measures the whole run in calendar days.
- Enforced only when a **vacation** request is filed; sick/personal stretches are not themselves capped but do count toward the run.
- A half-day means the employee was present that day, so it **bounds** (does not fill) a run.
- Exceeding the cap is a hard inline validation error, same style as the balance/overlap checks.

## Acceptance criteria

- [ ] A vacation request that would create a continuous absence longer than the cap is blocked with an inline error.
- [ ] The run is filled by all leave types, weekends, and holidays, and is bounded by a worked day.
- [ ] Adjacent existing pending/approved leave is included, so splitting requests cannot dodge the cap.
- [ ] Sick/personal-only stretches are not blocked, but extend a run that a vacation request would complete.
- [ ] A half-day bounds rather than fills a run.
- [ ] The cap value comes from central policy.
- [ ] Tests at the `validate_request` seam cover the block, run composition (types/weekends/holidays), adjacency, half-day bounding, and the vacation-only trigger, asserting external behavior only.

## Blocked by

- #24 (Holiday-aware day-counting + holidays store) — holidays fill the absence run.
- #23 (Central leave policy config) — the cap lives in central policy.

## Done (2026-06-16)

Implemented via TDD; all acceptance criteria met. Full suite 89 passed, no regressions.

- [x] A full-day vacation request creating a continuous absence longer than the cap is blocked with an inline error.
- [x] The run is filled by all leave types, weekends, and holidays, and bounded by a worked day.
- [x] Adjacent existing pending/approved leave is included (weekend-bridged split can't dodge the cap).
- [x] Sick/personal-only stretches are not themselves blocked, but extend a vacation run.
- [x] A half-day bounds rather than fills — a half-day request is never blocked by the cap.
- [x] The cap comes from central policy (`consecutive_limit["vacation"]`, default 15).
- [x] Tests at the `validate_request` seam: block, pass-within-limit, weekend-bridged adjacency, half-day-not-capped, sick-not-capped, sick-extends-vacation-run, holiday-extends-run.

**Key decisions:**
- **`continuous_absence_length(db, employee_id, start, end)`** in `requests.py`: a `non_working(d)` predicate (weekend OR holiday OR within the new full-day request OR within an existing **full-day** pending/approved leave) is extended left/right from the request to the bounding worked days; length is calendar days inclusive. Holidays fetched in a ±60-day window (comfortably over the cap); extension guarded at 400 iters.
- **Half-days bound, don't fill.** `active_full_leave_ranges` excludes half-day leave (the person is present), and the check is skipped entirely for a half-day *request* — so a half-day can never trip the cap. Matches the acceptance.
- **Vacation-only trigger.** The check runs only for `leave_type == "vacation"` full-day requests; sick/personal aren't capped but their full-day ranges still fill a vacation run.
- Error attached to the `start_date` block (via `setdefault`, so it doesn't clobber a past-date error). No infra change — pure read path over existing tables.

**Notes:** #28 (leave board) is the last remaining AFK task.
