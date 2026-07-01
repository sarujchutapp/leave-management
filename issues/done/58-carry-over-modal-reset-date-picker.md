# Carry-over modal: pick the reset date, forward-only anchor + transition note

- **Tracker:** #58
- **Labels:** ready-for-agent

---

## Parent

PRD #55 — Configurable carry-over reset date (leave-year start): #55

## What to build

Expose the reset date in `/control → Carry-over`. The modal gains a month/day picker
prefilled from the current setting. On admin-gated submit, the anchor is set to the
upcoming occurrence of the chosen month/day (**forward-only** — no recompute of past
periods), and the admin gets a note naming when the current leave period now ends (a
shorter **stub** or longer **stretch**) and stating that existing balances don't shift.
Carry-over enable/disable and the caps are unchanged. Leaving it at 1 Jan changes
nothing.

Blocked by both Slice 1 (the anchor / policy field + calendar seam) and Slice 2 (all
consumers re-based) so the reset date can't be made settable until balance, optimizer,
reports, and nudges all agree on the period — otherwise an admin could set 13 Apr while
reports still counted to 31 Dec.

## Acceptance criteria

- [ ] The Carry-over modal shows a month/day picker prefilled from the current reset date.
- [ ] A non-admin submit is rejected.
- [ ] An admin submit sets the anchor to the earliest occurrence of the chosen month/day strictly after today.
- [ ] Changing the date is forward-only — no past period is recomputed and no current balance shifts.
- [ ] The admin sees a note naming when the current leave period now ends (stub or stretch).
- [ ] Leaving the date at 1 Jan changes nothing.
- [ ] Carry-over enable / disable and the max-carry / max-total caps continue to work alongside the date.
- [ ] The submit acks within Slack's 3s window; the store + note run in the ack path (no post-ack work needed since nothing is recomputed).
- [ ] Tests cover the picker rendering (prefilled), the non-admin rejection, and the forward-only anchor + transition note on submit, following prior art in the carry-over tests in `tests/test_control.py`.

## Blocked by

- #56 — Leave-year calendar seam + policy reset date, balance & carry-in re-based
- #57 — Re-base downstream consumers on the current leave period

---

## Done

The `/control → Carry-over` modal now sets the leave-year reset date, forward-only.

- **Modal** (`leave/blocks.py`): a datepicker (`reset_date`) prefilled with this year's
  occurrence of the stored month/day — only the month & day are used; the year is ignored.
  `open_carry_over` / `update_carry_over_modal` pass `today` through.
- **Submit** (`leave/handlers.py`, ack path): re-checks admin (non-admin rejected), then
  `_reset_date_change` computes the forward-only move via `leave_year.reset_transition`:
  the new anchor is the earliest occurrence of the chosen month/day strictly after today,
  the current period keeps its start (pinned), and the admin gets a DM naming when the
  period now ends (a shorter **stub** or longer **stretch**) and that balances don't shift.
  Leaving it at 1 Jan is a no-op. Store + note run in the ack path (no recompute needed);
  the caps recompute stays post-ack.
- **Forward-only pin** (realises #56's deferred anchor): the policy stores `reset_anchor`
  (current period end / next reset) and `reset_period_start` (held start). The seam's
  `current_period(today, month, day, anchor, period_start)` rolls the pin forward
  deterministically (no write-on-read), then reverts to the plain recurrence past the
  anchor. Balance & carry (`leave/requests.py`) consume the pin; `period_key` is now
  **start-based** so the pinned current period reuses its existing key (no balance shift),
  and the carry roll-forward treats the one-time stub/stretch period as a single unit
  (`_next_period_start`). `recompute_carry_in` is pin-aware. `set_policy` preserves the
  pin across unrelated edits.
- **ADR-0004** updated: forward-only reset date now via a stored pin.

Tests: `tests/test_control.py` (prefilled picker, non-admin rejection, anchor = upcoming
occurrence, stub/stretch note, 1-Jan no-op, forward-only no-balance-shift) +
`tests/test_leave_year.py` (`current_period` pin roll-forward; start-based `period_key`).
Full suite green (344).

**Note:** `recompute_carry_in` / the operator script keep their year-based signature but
now build the rebuild day pin-aware. PRD #55 is fully delivered (#56 seam, #57 consumers,
#58 setter).
