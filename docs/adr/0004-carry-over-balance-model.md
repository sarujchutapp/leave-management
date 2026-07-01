# Carry-over balance model: central policy + per-person stored carry-in

V2 adds vacation **carry-over** (unused days roll into the next year, bounded by a
company-wide `max carry over` on what rolls out and `max total` on what's available
within a year). This breaks V1's clean model — "balance = allowance − used-this-year,
derived live, nothing stored, auto-resets at Jan 1" (ADR-0001) — because this year's
balance now depends on *last* year's leftover, which depends on the year before, and so
on back to the employee's first year. We resolve that with the **minimum** persisted
state: one **central leave policy** (per type: base allowance, `max carry over`,
`max total`) plus a **per-employee stored `carry_in`** computed once per year. Everything
within the current year stays derived live.

## The model

- **Policy is central, not per-employee.** Base allowance and both caps live in one place,
  so changing policy is a single edit. An employee may hold a personal allowance
  *override* only as an exception (e.g. a part-timer). (V1 stored allowance per-employee
  on each `employees` row; V2 moves the default to central config — a contained refactor
  of `balance`/`requests`/`db`.)
- **`carry_in` is the one persisted balance figure.** For year Y,
  `carry_in[Y] = min(leftover[Y-1], max_carry)` and
  `available[Y] = min(base_allowance + carry_in[Y], max_total)`. It is inherently
  per-person (depends on that individual's unused days). Base allowance is **never**
  overwritten by the inflated `available` — carry is always added onto the fresh base, or
  it would snowball past `max_total`.
- **Computed lazily, no scheduler.** The first time a balance is touched in a new year,
  compute `carry_in[Y]` once and store it (recursing once to backfill a missing prior
  year). Idempotent; a conditional write guards the concurrent-first-touch race.
- **Within-year `used` stays derived live**, so the retroactive-holiday refund (a
  newly-declared holiday lowers the cost of already-approved leave) keeps working
  unchanged. Only the cross-year hand-off is frozen.
- **Vacation only.** `sick` and `personal` have no carry and reset to their fresh
  allowance each year, exactly as today.

## Considered alternatives

- **Derive carry live across years (store nothing).** Keeps ADR-0001's purity, but
  computing today's balance means re-walking every prior year (one indexed query per year
  of history) on the cold-start-sensitive `/dayoff` path — and, worse, it is *wrong for
  new hires*: someone with no requests in past years has `used = 0`, so the recurrence
  hands them max carry-over for years they never worked. Correcting that needs a
  per-employee accrual-start year — i.e. stored state anyway. Storing `carry_in` is the
  same recurrence, memoized, and seeds new hires to 0.
- **Scheduled Jan-1 batch job.** Also correct, but adds EventBridge + a new entrypoint to
  a scale-to-zero stack (no scheduler exists today), processes everyone including inactive
  staff, and is a job that can silently fail to fire. Lazy compute self-triggers only for
  whoever actually checks a balance.
- **Snapshot the full balance (not just carry).** Would freeze within-year `used` too and
  break the live retroactive-holiday refund. Rejected — we freeze only the cross-year
  carry.

## Consequences

- **Departs from ADR-0001's "no stored balance counters."** Deliberate: `carry_in` is a
  low-churn value (one write per employee per year), not a hot mutable counter, and it is
  the smallest state that makes carry-over correct.
- A retroactive edit to an **already-closed** year (e.g. a holiday added for a past year)
  no longer reflows automatically into a later year's carry — re-run a small "recompute
  carry-in" operator script if a closed year ever needs fixing.
- Half-days make leftover/carry potentially fractional (e.g. `min(7.5, 5) = 5`); stored
  values move `int`→`Decimal` for these.

## Update: the leave year is a configurable, forward-only boundary

The "year" this model rolls carry over was originally the calendar year (auto-reset at
1 Jan). It is now a company-wide, configurable **reset date** (`reset_month` /
`reset_day` on the central policy, defaulting to 1 Jan). A pure **leave-year calendar
seam** (`leave/leave_year.py`) is the single home for the current period `[last reset,
next reset)`, the "upcoming occurrence", and the one-time stub/stretch transition — no
DB, no clock. The balance and carry-in read their window from the seam instead of
`today.year`.

The model above is unchanged in spirit — minimal stored state, lazy self-triggering
compute, nothing retroactive — with three refinements:

- **Period-keyed carry.** `carry_in` is keyed per reset period by the period's **start
  date**. A period starting 1 Jan keys to the bare year string (`"2026"`),
  byte-compatible with existing data (no migration); any other start keys to its ISO
  date, which stays unique even when a one-time stub puts two resets in one calendar
  year. Keying by the start (not the current reset month/day) is what lets a
  forward-only reset-date change keep the current period's key — its stored carry, and
  thus the balance, doesn't shift.
- **The advance self-triggers on the period, not 1 Jan.** The lazy carry-in compute
  fires the first time a balance is touched in a period not yet stored, rolling forward
  period by period; the concurrent-first-touch conditional write is unchanged.
- **Forward-only, via a stored pin.** Changing the reset date (admin, in `/control →
  Carry-over`) never recomputes or reclassifies a past period — it only moves where the
  current period next ends (a shorter stub or longer stretch). The change stores a pin
  on the policy — `reset_anchor` (the new next reset) and `reset_period_start` (the
  current period's held start) — which the seam rolls forward deterministically (no
  write-on-read) and drops back to the plain recurrence once the anchor is crossed. The
  one-time stub/stretch period is treated as a single unit by the carry roll-forward, so
  it is never split on the recurrence.
