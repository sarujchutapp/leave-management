# 2: expiring-quota flag on /burnout (covers 1b)

- Issue: #46
- Labels: ready-for-agent

---

## Parent

Burnout Board PRD: #44

## What to build

Add the **expiring-quota** signal to the `/burnout` board — delivering the
expiring-quota warning (1b) on the board rather than as a scheduled DM.

A new pure function computes the vacation a person will lose at year-end: the
remaining vacation that won't carry over (remaining minus the policy
`max_carry_over`, floored at zero), with days-left-in-year context. Surface it as
an additional flag on each board row, so a manager can see who is about to forfeit
unused days. It reflects the live policy cap and the current derived balance.

## Acceptance criteria

- [ ] A new pure function computes vacation that won't carry past year-end from remaining balance, the policy max-carry-over, and days left in the year.
- [ ] Each `/burnout` row shows the expiring-quota flag (e.g. "N days expiring Dec 31"), or clearly indicates none when nothing will expire.
- [ ] The flag reflects the live policy max-carry-over and the current remaining balance.
- [ ] The pure function is tested directly with hand-built inputs (prior art: the burnout pure-function tests), covering the some-expiring, none-expiring, and year-boundary cases; the flag's presence on the board is covered at the handler/board seam.

## Blocked by

- 1: /burnout board tracer — #45
