# DynamoDB migration 3/5: handler & validation flows end-to-end

> **Issue:** #13  
> **Labels:** AFK

---

## Parent

#10 — Migrate persistence from Postgres to DynamoDB (pay-per-usage)

## What to build

Make the full Slack handler and validation flows work end-to-end against the new DynamoDB-backed data layer, with no change to the user-facing behavior. With `requests.py` rewritten (slice 2), the handlers barely change — the main edit is that request IDs are now strings.

- Drop the three `int(body["actions"][0]["value"])` casts in the handlers — `request_id` is a `uuid4` string end-to-end and flows through Slack button/option payloads as-is.
- Confirm every handler path behaves identically: open-modal-with-balances, submit (validate → persist pending → DM manager ticket), auto-approve for top-of-chain, approve (calendar event + notify), decline (optional reason), the approver/non-pending guards, contact-admin for unregistered users, and all cancel paths (withdraw pending ticket, delete approved event + notify manager).
- Rewrite any remaining raw-SQL setup lines in `test_handlers.py`/`test_approval.py`/`test_cancel.py`/`test_validation.py` onto the data-access function seam. Slack/Calendar fakes are unchanged (they already pass values as strings).

## Acceptance criteria

- [ ] No `int(...)` casts remain on Slack-supplied request identifiers
- [ ] `/dayoff` modal shows balances; submit validates, persists pending, and DMs the manager ticket
- [ ] Top-of-chain (no manager) requests auto-approve and create a calendar event
- [ ] Approve creates the event + notifies; decline records reason + notifies; both guard approver identity and pending status
- [ ] Cancel: pending withdraws the manager ticket; approved-before-start deletes the calendar event and FYIs the manager; past leave immutable
- [ ] Unregistered users get the contact-admin message
- [ ] `test_handlers`, `test_approval`, `test_cancel`, `test_validation` pass — the entire suite is green offline on moto

## Blocked by

- #12