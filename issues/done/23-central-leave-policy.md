# Central leave policy config

- Tracker: #23
- Labels: AFK, ready-for-agent

## Parent

#21 — PRD: Leave Management V2

## What to build

Move the leave **policy** out of each employee row into one central place. Per leave type, the policy holds the **base allowance**, **max carry over**, **max total**, and the **consecutive-limit cap**. Balance math reads the central policy; an employee may carry a personal allowance **override** only as an exception (e.g. a part-timer).

End-to-end behavior:
- A central leave-policy config is the single source for base allowance and caps. Changing the company allowance or a cap is a single edit, not a per-employee sweep.
- Balance derivation reads the base allowance from the central policy by default, and from a per-employee override when one is set.
- The `/dayoff` modal continues to show correct remaining balances, now sourced from central policy (+ override where present).

This is the foundation ADR-0004 calls for; carry-over (its caps) and the consecutive limit (its cap) both read from this policy.

## Acceptance criteria

- [ ] Base allowance and the caps (max carry over, max total, consecutive limit) live in one central config, not duplicated per employee.
- [ ] Changing the central allowance changes every employee's balance without editing employee rows.
- [ ] A per-employee allowance override takes precedence over the central base for that employee only.
- [ ] The `/dayoff` modal and validation reflect the centrally-sourced allowance (and override).
- [ ] Existing balance behavior is preserved for employees without an override — no regression.
- [ ] Tests cover central-policy sourcing, the override path, and that balances change when central policy changes, over the moto `db` fixture, asserting external behavior only.

## Blocked by

- None - can start immediately

## Done (2026-06-16)

Implemented via TDD; all acceptance criteria met. Full suite 64 passed, no regressions.

- [x] Base allowance + caps (max carry over, max total, consecutive limit) live in one central policy, not per employee.
- [x] Changing the central allowance changes a no-override employee's balance without editing employee rows.
- [x] A per-employee `allowances` map is an override taking precedence over central (per leave type).
- [x] `remaining_balance`/`remaining_balances` (the `/dayoff` modal + validation paths) source allowance from central policy + override.
- [x] No regression for employees with explicit allowances (treated as overrides).
- [x] Tests cover central sourcing, override precedence, mixed override+central, caps storage, and the unseeded default, over the moto `db` fixture.

**Key decisions / deviations:**
- **Storage = a reserved `__policy__` item in the existing `employees` table**, accessed only through `leave/policy.py` (chosen with the user). Rationale: nothing scans `employees` (all access is keyed gets), so the reserved row is invisible to employee access patterns; the Lambda's existing `GetItem`-on-employees IAM already covers it, so this ships with **zero Terraform/infra change** (a dedicated table would have needed an IAM grant I can't `terraform apply`/verify here). It's a singleton behind an accessor, so moving to a dedicated table later is trivial.
- **Code default + DB override.** `get_policy` returns `DEFAULT_POLICY` (shipped baseline) when no item is set, and the DB item when an operator writes one via `set_policy` — giving no-redeploy editing without forcing a seed step. `seed.main()` writes the item on setup.
- **Allowances are now an override only.** `upsert_employee` no longer writes a default `allowances` map onto every employee; absent it, balances read central. `test_db.py` updated to the new contract; `add_employees.py` docstring updated (defaults now central).
- Caps (`max_carry_over`, `max_total`, `consecutive_limit`) are stored vacation-scoped per-type maps; **stored now, consumed by #26/#27.**

**Notes for next iterations:** #26 (carry-over) reads `max_carry_over`/`max_total` from `get_policy`; #27 (consecutive limit) reads `consecutive_limit["vacation"]`. If a dedicated `leave_config` table is ever wanted, repoint `policy.py` and migrate one item.
