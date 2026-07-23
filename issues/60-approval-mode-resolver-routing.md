# Approval mode: resolver + leave-submit routing + persistence (default-preserving)

- **Tracker:** #60
- **Labels:** ready-for-agent

---

## Parent

PRD #59 — Per-employee approval mode (auto / approval-needed): #59

## What to build

The backend for a per-employee **approval** setting, default-preserving and with no UI
yet (the reset value is exercised by setting it on the employee record directly). This is
the tracer bullet: it cuts through the employee record, one approval resolver, and the
leave-submit routing.

- Add an `approval` field (`auto` | `approval-needed`) to the employee record via the
  existing employee upsert, returned by the existing employee read.
- One **resolver** decides a request's mode: it reads the stored `approval`, and when the
  field is absent derives it to preserve today's behavior — `auto` when `manager_id` is
  `None` or equals the employee, else `approval-needed` (today's `_self_approves` rule).
  No backfill of existing records.
- Route `submit_leave` on the resolver: auto-approve (calendar + board, no ticket) iff the
  mode is `auto` OR the employee has no approver (`manager_id` is `None`); otherwise send a
  ticket to `manager_id`. When `manager_id` equals the employee the ticket goes to them and
  the existing approver check (clicker must equal `manager_id`) already lets them action it
  — that is proxy, with no special-casing.
- Re-express `_self_approves` via the resolver so the auto-vs-ticket rule has one home.

## Acceptance criteria

- [ ] The employee record round-trips an `approval` value of `auto` or `approval-needed` through the existing upsert/read.
- [ ] With no stored `approval`, the resolver returns `auto` for a self-managed / no-manager employee and `approval-needed` otherwise (today's behavior preserved).
- [ ] `approval = auto` auto-approves at submit (calendar + board, confirmation DM) with no ticket.
- [ ] `approval = approval-needed` with a distinct manager routes a ticket to that manager (unchanged from today).
- [ ] `approval = approval-needed` with the employee as their own manager routes the ticket to the employee, and they can approve/decline it themselves (proxy).
- [ ] An employee with no manager (`None`) still auto-approves regardless of `approval` (no approver to ticket).
- [ ] Cancel / withdraw / stale-ticket behavior on a proxy or manager ticket is unchanged.
- [ ] Every existing leave-submit and approval test passes unchanged (default behavior preserved).
- [ ] Tests cover the resolver (stored value + absent-field fallback) and the leave-submit routing (auto, manager ticket, proxy self-ticket, no-manager) following prior art in `tests/test_handlers.py` and `tests/test_approval.py`.

## Blocked by

None - can start immediately
