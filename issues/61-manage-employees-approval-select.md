# Manage-employees: Approval select (auto / approval-needed)

- **Tracker:** #61
- **Labels:** ready-for-agent

---

## Parent

PRD #59 — Per-employee approval mode (auto / approval-needed): #59

## What to build

Expose the approval setting in `/control -> Manage employees`. The modal gains an
"Approval" static_select (`auto` / `approval-needed`) alongside the manager picker,
prefilled from the employee's current setting on edit and defaulting to `approval-needed`
for a new person. On save the chosen value is stored on the employee record (via the
Slice 1 field). The manager stays required (self allowed for top-of-chain / proxy).

## Acceptance criteria

- [ ] The Manage-employees modal shows an "Approval" select with `auto` and `approval-needed` options, next to the manager picker.
- [ ] Editing an existing employee prefills the select with their current approval (or the derived default when they have none stored).
- [ ] A new person defaults to `approval-needed`.
- [ ] Saving stores the chosen approval on the employee record, so the Slice 1 routing then honors it (a report set to `auto` auto-approves; a top-of-chain person set to `approval-needed` gets a proxy ticket).
- [ ] The untouched-prefill fix still holds: leaving the approval (and name/manager) unchanged on an edit keeps the stored values.
- [ ] The manager remains required; picking yourself is still allowed.
- [ ] Tests cover the select rendering (prefilled on edit, default for new) and that a save persists the value, following prior art in the Manage-employees tests in `tests/test_control.py`.

## Blocked by

- #60 — Approval mode: resolver + leave-submit routing + persistence
