# Mutating an employee settles their in-flight leave

Removing or re-orging an employee — and the bulk Clear — now actively settle the
leave they touch, instead of blocking the action or leaving orphans behind.
Previously `delete_employee` removed only the employee row, and Clear deleted
request rows but left each manager's pending Approve/Decline message live: a
manager clicking a stale ticket crashed the bot (the employee/request came back
`None`), and an approved request's calendar event and board entry lingered with no
owner.

## The decision

- **Delete employee:** cancel the person's pending requests and withdraw their
  managers' tickets, remove their approved calendar events and board entries, then
  delete the row. Past (already-taken) leave is kept as history — it blocks nothing.
- **Edit manager (only when it actually changes):** cancel the employee's pending
  requests, withdraw the old manager's tickets, and DM the employee to re-file. The
  approver check reads the *current* manager, so the old ticket is already dead and
  the new manager never received one — re-filing routes it correctly.
- **Clear:** additionally withdraw every pending ticket in the pass it already makes
  over the requests, and wipe stored `carry_in`, so Clear is a true clean slate
  (reverses the earlier "Clear preserves carry_in" note).
- **Backstop:** `handle_approve` / `handle_decline_submit` are null-hardened, so any
  stale ticket that still gets clicked closes gracefully rather than crashing.
- These paths now run as **post-ack lazy listeners** on Lambda — they make slow
  Slack/calendar calls and must answer Slack's 3s ack first, like Clear and
  Carry-over already do.

## Considered alternatives

- **Block-and-tell** (refuse to delete or re-org while leave is in flight, mirroring
  the existing "still manages someone" guard). Simplest, but pushes manual cleanup
  onto the admin for a routine action; rejected once we were building the cleanup
  helper anyway.
- **Re-route the ticket** to the new manager on a manager change. Nicer for the
  admin, but re-implements the request flow (coverage radar, remaining balance, a
  fresh ticket); re-filing is clearer and far less code.

## Consequence

The admin surface gains real side effects: deleting a person silently cancels their
pending leave and clears their calendar/board entries. Accepted — the alternative is
orphaned data and a crash.
