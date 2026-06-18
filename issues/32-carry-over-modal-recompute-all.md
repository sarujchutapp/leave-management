# V3 #3: Carry-over modal + recompute-all carry-in

- **URL:** #32
- **Labels:** ready-for-agent

## Parent

V3: Admin control plane in Slack (`/control`) — #29

## What to build

The **Carry-over** sub-modal: an admin edits the central policy's `max carry over` and `max total` (vacation), and on save every employee's current-year carry-in is recomputed so balances aren't silently stale.

- The "Carry-over" button opens a modal pre-filled with current `max_carry_over` + `max_total` (from `get_policy`).
- On submit (admin re-checked), write the new caps via `set_policy` (ack phase).
- **Post-ack** (lazy listener on Lambda, inline in Socket Mode), run a new `recompute_all_carry_in(db, year)` that iterates every employee (a `Scan` on `employees`) and rebuilds the current year's stored `carry_in` from the stored chain using the new caps.
- `max_total` already applies live at balance read; the recompute is specifically to refresh the persisted `carry_in` that `max_carry_over` feeds.

## Acceptance criteria

- [ ] Carry-over modal opens pre-filled with current max carry over and max total.
- [ ] Submitting valid caps updates the central policy.
- [ ] After submit, every employee's stored current-year `carry_in` is recomputed from the stored chain under the new caps.
- [ ] The recompute runs post-ack (lazy listener on Lambda) so the Slack interaction acks within 3s.
- [ ] Non-admin submit is rejected; invalid input returns an inline error and writes nothing.
- [ ] Terraform: Lambda execution role gains `dynamodb:Scan` on the `employees` table.
- [ ] Offline tests cover: policy updated, `recompute_all_carry_in` rewrites stored carry_in for multiple employees, lowering max carry over reduces a stored carry_in.

## Blocked by

- V3 #1: /control skeleton (#30)
