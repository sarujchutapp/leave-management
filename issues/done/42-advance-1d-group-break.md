# 1d: group-break finder (shareable window)

- Issue: #42
- Labels: ready-for-agent

---

## Parent

V4 PRD: #36

## What to build

The **group-break finder** (the optimizer's second job), reached within `/advance`:
the caller picks a set of people and gets the longest window they can *all* be off at
once, rendered as shareable text.

End-to-end: extend `leave/optimizer.py` with the multi-person search (longest single
window where every selected member can be off simultaneously — rest-of-current-year,
vacation-only, each within their own balance and consecutive limit, built around each
member's existing bookings; tie-break earliest), a people-picker in the `/advance`
flow (any employee; the caller is always included), and a shareable-text result.

Privacy: the result reveals **only the shared window** — never any individual's
balance, and never whose constraint was binding. If no common window exists, say so.

## Acceptance criteria

- [ ] From `/advance`, the caller can pick people (caller auto-included) and receive the longest window the whole group can be off together.
- [ ] The window respects each member's own remaining vacation balance, consecutive limit, and existing bookings.
- [ ] The result reveals only the shared window — no individual balances, no indication of whose balance was the binding constraint.
- [ ] The result is rendered as copy-pasteable shareable text.
- [ ] An infeasible group (no common window) produces a clear "no common break" message, not an error.
- [ ] The multi-person search is covered by pure-function tests over hand-built per-member inputs, including the infeasible case.

## Blocked by

- 1a longest-break tracer: #37

---

## As-built (done)

- Pure core `leave/optimizer.py`: `Member(balance, cap, existing_ranges)` +
  `group_break(today, year_end, holidays, members) -> (start, end) | None`. Finds
  the longest single window every member can be off at once: for each member the
  window's new vacation days fit their balance and the continuous absence it forms
  (window + their adjacent leave/weekends/holidays) stays within their cap. The
  window must contain a real working day (a pure weekend isn't a break), is bounded
  to [today, year_end] (vacation-only, rest-of-year), and ties on length resolve to
  the earliest window. Returns ONLY the window — never a balance or which member
  bound it. Tested directly in `tests/test_optimizer.py` (longest common window,
  smallest-balance binds, built-around shared booking, infeasible→None, no members).
- Gather + UI in `leave/handlers.py` + `leave/blocks.py`:
  - `/advance` gains a "👥 Plan a group break" button (`GROUP_PICK_ACTION`).
  - `open_group_picker` opens a `multi_users_select` modal (`GROUP_CALLBACK_ID`);
    the caller is always included, so the picker is optional.
  - `submit_group_break(_apply)` gathers caller + picked employees (balance via
    `remaining_balance`, cap from policy, bookings via `active_full_leave_ranges`,
    company holidays), runs `group_break`, and DMs the caller copy-pasteable
    shareable text — or `GROUP_NO_WINDOW` when infeasible.
- `app.py`: `GROUP_PICK_ACTION` opens the picker synchronously; the submit runs
  the search post-ack (lazy listener on Lambda) so the ack stays under 3s for
  larger groups.

Decisions: window kept within the current year (rest-of-year, vacation-only);
half-days aren't modelled as group bookings (full-day `active_full_leave_ranges`,
like the consecutive-limit accounting). Unblocks #43 (Book mine), which adds a
"Book mine" button to this result reusing the #41 prefilled-modal mechanism.
