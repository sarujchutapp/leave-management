# V3 #2: Leave limits modal (allowance per type + consecutive limit)

- **URL:** #31
- **Labels:** ready-for-agent

## Parent

V3: Admin control plane in Slack (`/control`) — #29

## What to build

The **Leave limits** sub-modal: an admin edits the central policy's base allowance per leave type (sick / vacation / personal) and the consecutive limit, and the change takes effect immediately for everyone.

- The menu's "Leave limits" button opens a modal pre-filled with current values (from `get_policy`).
- On submit (admin re-checked), write the new `allowances` + `consecutive_limit` into the central `__policy__` item via the existing `set_policy`.
- Because balances are derived live, the new allowance/limit is reflected in every employee's `/dayoff` balances on the next read — no recompute needed.

## Acceptance criteria

- [ ] Leave limits modal opens pre-filled with the current allowances and consecutive limit.
- [ ] Submitting valid values updates the central policy (`get_policy` returns the new values).
- [ ] The new allowance flows live into `remaining_balances` for an employee without any stored-state migration.
- [ ] Non-admin submit is rejected.
- [ ] Invalid input (e.g. non-numeric / negative) returns an inline validation error and writes nothing.
- [ ] Terraform: Lambda execution role gains `dynamodb:PutItem` on the `employees` table (for the policy write).
- [ ] Offline tests cover: policy updated on submit, balances reflect new allowance, invalid input rejected.

## Blocked by

- V3 #1: /control skeleton (#30)
