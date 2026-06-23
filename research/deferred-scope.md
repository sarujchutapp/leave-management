# Deferred scope — next-level features

Things we deliberately pushed to a later iteration during the design grill, each
with the trigger that should revive it. Companion to `next-level-features.md`.

## Blocked on a scheduler (parked pending advisor)

The stack has **no scheduler** today — ADR-0004 deliberately avoided EventBridge
(scale-to-zero, no entrypoint, "a job that can silently fail to fire"). Every
proactive feature waits on that one decision:

- **1b** expiring-quota warning
- **1c** whole-year plan (January push)
- **Pillar 2** burnout **warning** — the proactive sweep. Burnout is the *absence*
  of events, so it can't be reactive like Coverage Radar; it needs a scheduled
  sweep over everyone. (The burnout **report** ships now — see below.)

Building a scheduler **reverses ADR-0004** → it warrants its own ADR when decided.
Contained change (one EventBridge schedule + a fork in `lambda_handler.handler`
to tell a scheduled invoke from a Slack HTTP one + a job module), but must be
**idempotent** — EventBridge→Lambda is async and retries twice.

## 1a — longest-break finder

- **v2:** horizon beyond rest-of-current-year (e.g. rolling 12 months). Blocked on
  next-year carry-in being computed — messy across the year boundary.

## 1d — group break

- **v1:** shareable text + "Book mine" (requester's own slice only; reuses 1a's
  prefilled apply modal). No unsolicited DMs to others.
- **v2:** invitation / accept ticket — each selected member gets Accept/Decline;
  Accept creates *that member's* normal pending request (still manager-approved).
  Adds multi-party state + recompute-on-decline. Build once people actually rally
  around the computed windows.
- **v2:** same next-year-horizon upgrade as 1a.

## Coverage Radar

- **v1:** warn on **≥1** peer overlap, fixed threshold, computed at **submit**
  (static on the ticket).
- **v2:** **configurable threshold in `/control`** — this number is the seed of
  Pillar 3's enforced capacity cap.
- **v2:** **recompute-at-approve** (fresh) instead of static-at-submit, to close
  the first-ticket blind spot (earliest ticket for a contested week is blind to
  later requests).

## Pillar 2 — Burnout

No standalone "board" surface. Splits into:

- **Burnout report (now):** a third report type in `/control`'s existing report
  picker (alongside quota + per-person history). Ranks the team by **no-break
  stretch** (days since last *taken* leave, extended by whether/when anything is
  booked ahead), with supporting flags (low remaining allowance late in the year,
  long consecutive working stretch). Explainable — every flag says why; no opaque
  score.
- **Burnout warning (needs scheduler):** the proactive DM to the at-risk person
  and/or manager. Parked above.

## Pillar 3 — Fair Allocation

- Sequence last. Needs an **enforced capacity cap** (grows out of Coverage Radar's
  `/control` threshold) **+ multi-year request history** to rotate on. Socially
  delicate — keep the rule transparent.
