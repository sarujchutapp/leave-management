# V3 #4: Clear — typed-confirm wipe of requests/calendar/board

- **URL:** #33
- **Labels:** ready-for-agent

## Parent

V3: Admin control plane in Slack (`/control`) — #29

## What to build

The **Clear** sub-modal: an admin wipes all leave requests + their calendar events + resets the board in one action, guarded by a typed confirmation word. Employees, central policy, and holidays are kept.

- The "Clear" button opens a modal with a text field requiring a confirmation word (e.g. `CLEAR`); a non-matching value returns a validation error and wipes nothing.
- Extract `clear_requests.py`'s logic into a reusable function so both the handler and the existing script call it: scan `leave_requests`, delete each row's calendar event, batch-delete the rows, and `reset_board`.
- Keeps employees, the reserved central-policy item, holidays, and stored `carry_in` (matching today's script behaviour).
- The wipe runs **post-ack** (lazy listener on Lambda, inline in Socket Mode).

## Acceptance criteria

- [ ] Clear modal requires a confirmation word; a wrong/blank value returns an inline error and deletes nothing.
- [ ] With the correct word, all `leave_requests` rows are deleted, their calendar events removed, and the board reset.
- [ ] Employees, central policy, and holidays remain intact after a clear.
- [ ] The existing `clear_requests.py` script delegates to the same extracted function (no behaviour drift).
- [ ] The wipe runs post-ack so the interaction acks within 3s.
- [ ] Non-admin submit is rejected.
- [ ] Terraform: Lambda execution role gains `dynamodb:Scan` + `dynamodb:DeleteItem` on the `requests` table.
- [ ] Offline tests cover: wrong word = no-op, correct word wipes rows + deletes fake calendar events + resets board, employees/policy preserved.

## Blocked by

- V3 #1: /control skeleton (#30)
