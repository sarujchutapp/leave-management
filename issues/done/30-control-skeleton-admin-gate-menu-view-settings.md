# V3 #1: /control skeleton — admin gate + menu + View Settings

- **URL:** #30
- **Labels:** ready-for-agent

## Parent

V3: Admin control plane in Slack (`/control`) — #29

## What to build

The `/control` skeleton end-to-end: a new admin-only slash command that opens a menu modal, gated by an admin allowlist, plus the read-only **View Settings** path to prove the whole plumbing with zero destructive risk.

- `/control` (no args) checks whether the invoking Slack user is an **Admin** (member of an injected allowlist sourced from a non-secret `SLACK_ADMIN_IDS` env var). Non-admins get nothing actionable.
- For an admin, it opens a single **menu modal** whose buttons name the admin actions (Leave limits, Carry-over, Clear, Report, Manage employees, View settings). Buttons whose features aren't built yet may be present-but-inert or omitted — implementer's choice, but the menu and routing must exist.
- **View Settings** is fully implemented in this slice: it shows the current central policy (allowances per type, max carry over, max total, consecutive limit) read-only, via the existing `get_policy`.
- The admin check is re-applied on every sub-modal submit (defense in depth), so later slices inherit it.

This is the tracer bullet: command → admin gate → menu → a sub-modal showing real data. No new DynamoDB permissions are needed (policy read is already granted).

## Acceptance criteria

- [ ] `/control` invoked by a non-admin does not open the admin menu (no actionable response).
- [ ] `/control` invoked by an admin opens the menu modal listing the admin actions.
- [ ] The admin allowlist is injected into the handler(s), not read from the environment inside them, so tests can set admin/non-admin.
- [ ] View Settings displays the current policy (allowances, max carry over, max total, consecutive limit) read-only.
- [ ] The admin gate is re-checked on sub-modal submit, not only at command time.
- [ ] Command + handlers registered in the app factory for both run modes (Socket Mode + Lambda).
- [ ] `SLACK_ADMIN_IDS` documented in `.env.example` and wired as a Terraform variable / Lambda env var.
- [ ] Offline tests (moto + fakes) cover: non-admin rejected, admin opens menu, View Settings renders current policy. `is_admin` tested directly.

## Blocked by

None - can start immediately.
