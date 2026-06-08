# Leave Management via Slack — Design Decisions

Decisions converged during grilling session, 2026-06-05.

## Context

- Real internal tool, small scale (~5–20 users, a few managers).
- Tested with proxy data in a personal Slack workspace before migrating to the real one.
- Pain point: requesting absence requires DMing the manager, who checks and records it manually. Replace with one slash command + one-click approval + automatic bookkeeping.

## Flow

1. `/leave` → Slack **modal** (Block Kit): leave-type select, native date pickers, optional reason, shows requester's remaining balance.
2. On submit, validate:
   - `end ≥ start`
   - `start ≥ today` (no backdating, any type)
   - enough quota (weekday count ≤ remaining)
   - no overlap with requester's own pending/approved requests
   - Failures shown inline in the modal.
3. Valid → ticket DM'd to the mapped manager: employee, type, dates, reason, remaining-balance context, Approve / Decline buttons.
4. **Approve** → status updated, Google Calendar event created, employee notified.
   **Decline** → optional reason via small modal, employee notified.
   Handler verifies clicker = mapped manager.
5. **Cancel:**
   - pending — anytime
   - approved — only before start date (calendar event deleted, manager gets FYI)
   - past leave immutable
6. No reminders or auto-expiry in v1; a pending request whose dates pass becomes inert.

## Data (PostgreSQL — Supabase/Neon free tier)

- `employees`: slack_user_id (PK — Slack user ID, not username), real_name, manager_id (nullable), per-type annual allowances.
  - **Pre-seeded; registration out of scope.**
  - `manager_id = NULL` → requests **auto-approve** (top of chain).
  - Unregistered users get a "contact admin" error.
- `requests`: employee, type, start, end, status (`pending/approved/declined/cancelled`), reason, decline_reason, calendar_event_id, timestamps. Full history kept.
- **No stored balance counters** — `remaining = allowance − SUM(weekdays of approved requests this calendar year)`. Resets automatically at calendar-year boundary.
- Leave types: small fixed set (`sick`, `vacation`, `personal`).
- Day counting: **weekdays only** (Mon–Fri). Thai public holidays punted to v2 (documented workaround: split the request around the holiday).
- NoSQL considered and rejected: data is relational (foreign keys, SUM aggregations); document DB would force denormalized counters and consistency bugs.

## Public calendar

- Shared Google Calendar "Team Leave", owned by a personal Gmail (tenant-proof; ownership transferable later).
- Bot writes via **service account** (calendar shared to it with "Make changes to events").
- All-day events created **on approval only** (not pending), deleted on cancel.

## Stack

- Python: `slack-bolt` (**Socket Mode** — no public URL, runs locally during test phase), `google-api-python-client`, Postgres driver.
- Deploy to a free host (Render/Railway/Fly) later without code changes.

## Explicitly out of scope (v1)

- Half-days
- Public holidays in quota math
- Registration / admin UX (DB seeded manually)
- Approval chains / backup approvers
- Reminders / pending-request expiry
- Backdating
- Web UI (request form and queries live entirely in Slack; month view is Google Calendar)
