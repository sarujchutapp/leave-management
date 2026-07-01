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
