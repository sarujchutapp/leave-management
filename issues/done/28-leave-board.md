# Leave board (shared live grid)

- Tracker: #28
- Labels: AFK, ready-for-agent

## Parent

#21 — PRD: Leave Management V2

## What to build

A single shared **leave board** in a dedicated Slack channel: one live-updating message that renders the current month as a grid (people × days) showing who's off, replacing the old "fill an Excel sheet, screenshot it, drop the picture in a group chat" ritual. Everyone looks at the same message; nobody runs a command.

End-to-end behavior:
- A pure block-builder renders the month grid with glyphs distinguishing full day, morning half, afternoon half, and holiday.
- A board-update function maintains one canonical message in the dedicated channel, edited in place (`chat_update`) whenever leave is approved or cancelled, called from the existing approve/cancel handlers.
- When the month turns, a fresh message is started for the new month.
- Rendering is text/Block Kit for now (editable in place, no new dependencies); a rendered image is a possible later enhancement and is out of scope here.

## Acceptance criteria

- [ ] Approving or cancelling leave updates the single board message in the dedicated channel (no new message per change within a month).
- [ ] The grid shows each person's leave for the month, distinguishing full / morning-half / afternoon-half / holiday.
- [ ] A new month starts a fresh board message.
- [ ] The board reflects only the appropriate statuses (approved leave; cancellations removed).
- [ ] The pure block-builder is unit-tested on structure (as the modal/ticket builders are); the handler seam is tested by asserting FakeSlackClient issued the board update on approve/cancel. Exact rendered text is not asserted.

## Blocked by

- #22 (Half-day leave) — the grid distinguishes morning/afternoon halves.
- #24 (Holiday-aware day-counting + holidays store) — the grid distinguishes holidays.

## Done (2026-06-16)

Implemented via TDD; all acceptance criteria met. Full suite 97 passed, no regressions.

- [x] Approving or cancelling updates the single board message in place (chat_update); a new month posts a fresh message.
- [x] The grid renders each person's leave for the month, distinguishing full (`#`) / morning (`\`) / afternoon (`/`) / holiday (`*`).
- [x] Reflects approved leave only: added on approve/auto-approve, removed on approved-cancel.
- [x] Pure `build_board_blocks` unit-tested on structure; handler seam asserted via FakeSlackClient (approve posts to the board channel; approved-cancel drops the entry). Exact text not asserted.

**Key decisions (chosen with the user):**
- **Denormalized board state (Option 1), no scan.** The month's approved leave is a reserved `__board__` item in the employees table (`channel`, `month`, `ts`, `entries`), updated incrementally from approve/cancel — no cross-employee scan, honoring ADR-0001. Uses the existing `GetItem`/`UpdateItem` on employees (granted in #26) — **no new IAM**.
- **Single live message, fresh per month.** `update_board` posts when the month turns (or no message yet) and `chat_update`s in place otherwise; `ts` persisted on the board item.
- **Channel via `LEAVE_BOARD_CHANNEL`** env var; absent it the board is a no-op (so existing handler tests with no channel are unaffected, and the feature is opt-in). Added a Terraform `leave_board_channel` variable + Lambda env var.
- **Rendering is provisional** text/Block Kit (monospace grid), per the grilling decision — editable in place, no deps. Marked for visual review before locking; an image renderer is a possible later enhancement.

**⚠️ Caveats / for review:**
- **Provisional rendering** — the user wanted to eyeball the Block Kit grid; please review on a real Slack (mobile width especially) before considering it final.
- **Backfill gap (inherent to Option 1):** the board only reflects leave that flows through approve/cancel after launch; pre-existing approved leave won't appear until touched. A one-time backfill script could populate it if desired (out of scope here).
- **Terraform** `leave_board_channel` var + env are `fmt`/`validate`-clean but **not `terraform apply`-verified** here. Operator must set the channel ID and invite the bot to that channel.

This was the last V2 AFK task (#22–#28 all complete).
