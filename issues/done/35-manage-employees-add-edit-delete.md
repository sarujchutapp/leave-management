# V3 #6: Manage employees (add/edit/delete with manager guard)

- **URL:** #35
- **Labels:** ready-for-agent

## Parent

V3: Admin control plane in Slack (`/control`) — #29

## What to build

The **Manage employees** sub-modal: an admin adds, edits, and removes employees from Slack, replacing the `add_employees.py` script for onboarding/offboarding.

- **Add / edit**: pick the person and (optionally) their manager via Slack user-picker elements (member IDs supplied directly, no copying), set name and an optional allowance override. Reuses `upsert_employee`.
- **Delete**: removing an employee is **block-and-tell** — if the target is still listed as any employee's `manager_id`, the submit is rejected with a message naming the reports that still point at them; nothing is deleted. The admin must re-assign those reports via the edit flow first, then retry. No automatic re-parenting.
- A regular employee (no reports) deletes after the normal confirm.
- Listing reports for the guard uses a `Scan` on `employees`.

## Acceptance criteria

- [ ] Add creates a new employee (name, manager, optional override) using Slack user-pickers for IDs.
- [ ] Edit updates an existing employee's name / manager / override.
- [ ] Deleting an employee who is nobody's manager succeeds.
- [ ] Deleting an employee who is still someone's manager is rejected with a message naming the blocking reports; no rows are deleted and no one is re-parented.
- [ ] After re-assigning the reports via edit, the manager can then be deleted.
- [ ] Non-admin submit is rejected.
- [ ] Terraform: Lambda execution role gains `dynamodb:Scan` + `PutItem` + `DeleteItem` on the `employees` table.
- [ ] Offline tests cover: add, edit, delete-non-manager succeeds, delete-manager blocked with report names, delete after reassignment succeeds.

## Blocked by

- V3 #1: /control skeleton (#30)
