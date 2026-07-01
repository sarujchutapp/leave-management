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
