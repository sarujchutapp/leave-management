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
