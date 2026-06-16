# Vacation carry-over (lazy carry-in)

- Tracker: #26
- Labels: AFK, ready-for-agent

## Parent

#21 — PRD: Leave Management V2

## What to build

Add vacation **carry-over**: unused vacation rolls into the next year, bounded by `max carry over` (what rolls out) and `max total` (what's available within a year). Applies to **vacation only** — sick and personal reset to their fresh allowance each year. See ADR-0004.

End-to-end behavior:
- For year Y: `carry_in[Y] = min(leftover[Y-1], max_carry)` and `available[Y] = min(base_allowance + carry_in[Y], max_total)`. The base allowance is never overwritten by the inflated available.
- `carry_in` is the one persisted balance figure, stored per-employee, computed **lazily** on first balance access in a new year (idempotent; a conditional write guards the concurrent-first-touch race; recurse once to backfill a missing prior year). A new hire seeds to `0`.
- Within-year `used` stays derived live, so the retroactive-holiday refund keeps working.
- No mid-year expiry — carried days behave like fresh allowance all year.
- A small "recompute carry-in" operator script exists for fixing an already-closed year.

## Acceptance criteria

- [ ] Vacation balance in a new year reflects capped carry-in from the prior year's leftover; sick/personal still reset.
- [ ] `max carry over` caps what rolls out; `max total` caps in-year availability (both from central policy).
- [ ] `carry_in` is computed once and stored per-employee; recomputation is idempotent and does not double-count.
- [ ] A new hire (no prior-year requests) starts with `carry_in = 0`, not a hallucinated full carry.
- [ ] Within-year `used` is still derived live (a retroactive holiday still refunds in the current year).
- [ ] A recompute operator script can rebuild `carry_in` for an employee/year.
- [ ] Tests over the moto `db` fixture cover caps, new-hire seeding, lazy idempotency, and preserved live within-year behavior, asserting external behavior only.

## Blocked by

- #23 (Central leave policy config) — reads base allowance and the caps from central policy.

## Done (2026-06-16)

Implemented via TDD; all acceptance criteria met. Full suite 82 passed, no regressions.

- [x] New-year vacation balance reflects capped carry-in from the prior year's leftover; sick/personal still reset.
- [x] `max carry over` caps the rolled-out leftover; `max total` caps in-year availability (both from central policy).
- [x] `carry_in` is stored per-employee (a `{year: days}` map on the employee item), computed lazily; recomputation is idempotent (deterministic) and does not double-count.
- [x] New hire (no stored carry) seeds `carry_in = 0` for their first observed year — no hallucinated carry.
- [x] Within-year `used` stays derived live (a retroactive holiday still refunds under carry — `test_within_year_retroactive_holiday_still_refunds_under_carry`).
- [x] Recompute operator script (`recompute_carry.py` → `recompute_carry_in`) rebuilds carry_in[year] from the stored chain.
- [x] Tests over moto cover caps, new-hire seeding, idempotency, sick-resets, retroactive-under-carry, recompute.

**Key decisions / deviations:**
- **Roll-forward-from-stored, seed-0-on-first-sight.** `carry_in_for` rolls `carry_in[Y] = min(max(available[Y-1] − used[Y-1], 0), max_carry)` forward from the latest *stored* year; an employee with no stored carry is treated as starting this year (0). This is exactly what prevents the new-hire phantom-carry bug ADR-0004 flagged — carry is never computed from absent history, only from a stored prior year.
- **Availability formula refined.** ADR-0004 wrote `available = min(base + carry_in, max_total)`. That's correct when `base ≤ max_total`, but a per-person override above `max_total` would have its *base* capped down — wrong. Implemented as `base + max(0, min(carry_in, max_total − base))`: `max_total` caps how much carry adds on top, never reduces the base grant. (Caught by an existing override test regressing — good signal.)
- **Storage = a `carry_in` map on the employee item** (reserved-key policy item is separate). The one persisted balance figure, per ADR-0004; everything else stays derived live.
- **Idempotency via determinism**, not a conditional write. ADR-0001 already accepts read-then-write at this scale; recomputing yields the same number, so a concurrent first-touch just writes the same value (no double-count). A conditional write is the cheap future hardening if ever needed.

**⚠️ Infra (written, not apply-verified):** the lazy carry write is an `UpdateItem` on the **employees** table, which the Lambda's IAM didn't previously grant. I extended the employees IAM statement to `["dynamodb:GetItem", "dynamodb:UpdateItem"]` (sid renamed `EmployeesReadWrite`) in `terraform/main.tf`. `terraform fmt`/`validate` pass, but I could not `terraform apply` here — **a human must apply** before production. (Alternative considered: have a scheduled/operator job seed carry_in so the Lambda only reads — rejected to keep the chosen lazy-on-read design from ADR-0004.)

**Notes for next iterations:** #27 (consecutive limit) and #28 (leave board) remain. #27 reads `consecutive_limit["vacation"]` from policy.
