# Leave-year calendar seam + policy reset date, balance & carry-in re-based (default 1 Jan)

- **Tracker:** #56
- **Labels:** ready-for-agent

---

## Parent

PRD #55 — Configurable carry-over reset date (leave-year start): #55

## What to build

Introduce a company-wide, configurable **leave-year reset date** at the data + logic
layers, defaulting to **1 January** so behavior is identical to today. This is the
tracer bullet: it cuts through policy → a new leave-year calendar seam → the derived
balance and carry-in, proven to reproduce today's behavior at the default and to shift
correctly when configured. No UI yet — the reset date is exercised by setting it on the
policy directly.

- A **pure leave-year calendar seam** computes the current leave period `(start, end)`
  and the next reset date from `(today, reset month/day, anchor)` — no DB, no side
  effects. It is the single home for the "upcoming occurrence" and stub/stretch
  transition logic, replacing the scattered `today.year` / `date(today.year, 1, 1)` /
  `date(today.year, 12, 31)` assumptions.
- The **central policy** gains the reset month/day plus a forward-advancing anchor (the
  next reset date), defaulting to 1 Jan. A fresh or untouched policy behaves as today.
- The **derived balance** (`remaining_balance`, `remaining_balances`, approved-weekdays
  used, `carry_in_for`) computes over the current leave period from the seam instead of
  the calendar year. The **lazy carry-in advance** triggers when today has passed the
  stored anchor (not "new calendar year"): it computes carry for the period that just
  ended, advances the anchor one year to the same month/day, and stores it — idempotent,
  keeping the concurrent-first-touch conditional-write guard.
- `carry_in` is **keyed per reset period**, unique even when the one-time stub transition
  puts two resets in one calendar year (e.g. 1 Jan then 13 Apr 2026). The 1-Jan default
  stays byte-compatible with existing stored `carry_in` keys so untouched systems need no
  migration.
- Holiday-aware "used" counting reads holidays across the **period window** (which may
  span two calendar years) rather than a single calendar year.
- **Forward-only:** changing the reset date never recomputes or reclassifies past
  periods.
- Update **ADR-0004** to note the leave year is now a configurable, forward-only boundary
  (still minimal stored state, lazy self-triggering compute, nothing retroactive).

## Acceptance criteria

- [ ] At the default (1 Jan) reset date, every existing balance and carry-over test passes unchanged.
- [ ] The pure calendar seam returns calendar-year bounds for 1 Jan, a stub period when the date is set ahead-of-today this year, and a stretch period when the date has already passed this year.
- [ ] The next reset is the earliest occurrence of the configured month/day strictly after today; the current period is `[last reset, next reset)` with positive length.
- [ ] With a non-1-Jan reset date, remaining balance is computed over the current period and quota returns to full on the reset date.
- [ ] Unused vacation carries over (capped by max carry over / max total) at the configured reset date, not 31 Dec.
- [ ] The lazy carry-in advance fires when today passes the stored anchor and advances it one year; it is idempotent and does not double-apply.
- [ ] `carry_in` is stored uniquely per reset period, including when two resets fall in the same calendar year (stub transition).
- [ ] A new hire seeds carry to 0 for periods before they started (unchanged).
- [ ] The within-period retroactive-holiday refund still lowers used for already-approved leave.
- [ ] Changing the reset date does not recompute or reclassify any past period.
- [ ] Tests cover the pure calendar seam (default / stub / stretch / annual recurrence) and the balance seam over a non-1-Jan period, following prior art in `tests/test_balance.py`, `tests/test_optimizer.py`, and `tests/test_carryover.py`.

## Blocked by

None - can start immediately
