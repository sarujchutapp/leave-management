# Pending leave reserves quota

`validate_request`, the hard gate at submit time, now checks a request against
*free* days — the approved-only remaining balance **minus what's already pending** —
instead of approved-only. Pending leave is treated as reserved quota: you can't file
a request against days already spoken for by pending or approved leave. This
**supersedes ADR-0008**, which deliberately kept the gate approved-only.

## Why the reversal

ADR-0008 kept the validator approved-only so a request wouldn't be blocked on quota a
pending (possibly-to-be-declined) request hadn't actually consumed. But that left a
hole it named without closing: two pending requests that each fit the balance alone
both pass, and nothing re-checks at approval — so a manager approving both drives the
balance negative through the normal flow (not just via an admin cap cut, which is the
one intended negative). The gap was real: file A (fits), file B (fits, because A is
still only pending), approve both → overshoot.

Two ways to close it:

- **Re-check at approval time.** Requests stay valid at submit; the *second approval*
  fails. That produces a pile of pending tickets where "once one is approved you must
  disable the others" — fail-late, and exactly the mess we want to avoid.
- **Reserve at request time** (this decision). The second request that would overshoot
  is rejected at submit. No stacked pending, no ticket that later can't be approved,
  and `handle_approve` stays dumb — approving any subset of reserved requests can never
  overshoot. Fail-fast.

It also collapses the asymmetry ADR-0008 introduced: the optimizer already plans
against `remaining − pending` (free days). The validator now gates on that same free
notion, so a suggested break and an accepted request agree by construction — the
invariant ADR-0008 wanted ("every suggested break passes `validate_request`") holds,
now as an equality rather than a subset.

## The decision

- The balance check subtracts pending: `free = remaining_balance − pending_days`, for
  the requested leave type. Applies to **all leave types**, not just vacation.
- `pending_days(db, employee_id, leave_type, today)` generalizes the old
  vacation-only `pending_vacation_days`; it's one `by_employee` query, the same one
  `remaining_balance` already makes — **no extra I/O**. A declined/cancelled request
  stops counting on the next live read, so a reserved hold releases itself.
- The manager's approval ticket keeps showing the **approved-only** "X left" — the
  ledger figure — not free-after-pending. Only the gate uses free.

## Consequence

While a request sits pending, its days are reserved: an employee can't book more than
their remaining-after-pending until the manager decides (or the request is
cancelled/declined, which frees it live). Accepted — "requesting reserves the days" is
the clearer mental model, and it makes over-approval structurally impossible rather
than relying on a manager to catch it. The intended negative balance (admin lowering
an allowance/cap below days already taken) is unaffected — that path doesn't go
through `validate_request`.
