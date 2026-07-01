# Re-base downstream consumers (advance, reports, nudges) on the current leave period

- **Tracker:** #57
- **Labels:** ready-for-agent

---

## Parent

PRD #55 — Configurable carry-over reset date (leave-year start): #55

## What to build

Re-base every downstream consumer of "the year" onto the current leave period from the
Slice 1 calendar seam, so a non-1-Jan reset date is respected everywhere balance-adjacent
logic reads a year boundary. At the 1-Jan default these are identical to today.

- The `/advance` optimizer and group-break horizon ("rest of the year", currently to
  31 Dec) becomes the rest of the current leave period (up to the next reset), with
  holidays read over that window.
- Reports compute per-type used / remaining over the current leave period.
- Burnout / year-end nudges reference the current leave period ("use it before it
  resets") rather than the calendar year.

## Acceptance criteria

- [ ] `/advance` and the group-break finder suggest breaks bounded by the next reset (period end), not 31 Dec.
- [ ] Report figures (per-type used / remaining) are computed over the current leave period.
- [ ] Burnout / year-end nudges reference the current leave period's remaining window.
- [ ] Holiday windows in these paths span the current period (which may cross two calendar years).
- [ ] At the default 1-Jan reset date, all three consumers behave identically to today (existing advance / report / burnout tests pass unchanged).
- [ ] Tests cover each consumer over a non-1-Jan period, following prior art in `tests/test_advance.py` / `tests/test_optimizer.py`, the report tests, and `tests/test_burnout.py` / `tests/test_burnout_board.py`.

## Blocked by

- #56 — Leave-year calendar seam + policy reset date, balance & carry-in re-based

---

## Done

Re-based all three downstream consumers of "the year" onto the current leave period
from the #56 seam. At the 1-Jan default they are byte-identical to before (all prior
advance/report/burnout tests pass unchanged).

- **/advance + group-break** (`leave/handlers.py`): new `_optimizer_horizon(db, today)`
  returns the current period's last day (day before the next reset — 31 Dec by default)
  and the holidays across the window; both `_suggest_breaks` and `submit_group_break_apply`
  pass it as the optimizer horizon, so suggestions are bounded by the next reset, not
  31 Dec. Holidays read via `holidays_between` over the window (may span two calendar years).
  The optimizer itself was already horizon-parameterized — no change needed.
- **Reports** (`leave/report.py`): the burnout signals now compute over the current
  period — `no_break_stretch` anchors at the period start, `longest_working_stretch` and
  holidays span the period, and `days_left` counts down to the next reset. (Per-type
  used/remaining were already period-based via #56's `remaining_balances` / `carry_in_for`.)
- **Nudges** (`leave/burnout.py` + `leave/handlers.py`): `no_break_stretch` gained an
  optional `period_start` anchor; the year-end nudge copy now says vacation "expire[s] when
  your leave year resets" rather than "on Dec 31"; `expiring_quota` doc updated.

Tests: non-1-Jan cases added in `tests/test_advance.py` (advance + group-break bounded by
reset), `tests/test_burnout.py` (period-start anchor), `tests/test_burnout_board.py`
(stretch + days_left over the period), `tests/test_control.py` (report figures over the
period). Full suite green (335).

**Note for #58 (now unblocked):** expose the reset date in `/control → Carry-over` using
`leave_year.reset_transition`; decide whether a stored anchor/period-start is needed for a
mid-period forward-only change (see #56's note). Also: `recompute_all_carry_in` /
`recompute_carry_in` remain year-keyed (a #56 documented limitation) — fine for the 1-Jan
default; revisit if a non-default recompute is needed.
