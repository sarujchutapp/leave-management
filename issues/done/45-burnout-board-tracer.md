# 1: /burnout board tracer (manager view of direct reports, ranked)

- Issue: #45
- Labels: ready-for-agent

---

## Parent

Burnout Board PRD: #44

## What to build

The first tracer through the **Burnout Board**: a new manager command `/burnout`
that shows the caller their direct reports ranked by burnout risk, as an
interactive board.

Manager-gated: usable only by someone who manages at least one person (detected
from the existing `manager_id` hierarchy — no new "team" model); a caller who
manages no one gets a clear "you don't manage anyone" reply. The board lists the
caller's **direct reports**, ranked by **no-break stretch** (longest first, name
as tie-break), each row showing the explainable flags that already exist: days
since last taken leave (the no-break stretch), remaining vacation vs. days left in
the year, and longest consecutive working stretch. Scope is strictly the caller's
direct reports (the privacy guardrail — another team's people never appear);
reserved/config items are excluded as elsewhere.

Reuse the existing pure burnout signal functions, and factor the per-employee
signal computation currently inside the #39 burnout CSV builder into a shared
helper so the board and the CSV report compute identically (no drift). Because
building the board reads several records, deliver it the way the `/control` report
does — ack within Slack's window, then post — so the command never times out.

No Nudge button yet and no expiring-quota flag yet (later slices).

## Acceptance criteria

- [ ] A manager (≥1 direct report) running `/burnout` sees their direct reports ranked by no-break stretch, longest first.
- [ ] Each row shows the supporting flags — days since last taken leave, remaining vacation vs. days left in the year, and longest consecutive working stretch — explainable, never an opaque score.
- [ ] The board is scoped to the caller's direct reports only; another manager's reports never appear, and reserved/config items are excluded.
- [ ] A caller who manages no one gets a clear "you don't manage anyone" reply, not an error or an empty board.
- [ ] An employee who has never taken leave is handled sensibly (stretch measured from a defined start, not an error).
- [ ] The board and the existing `/control` burnout CSV report (#39) compute the same signals via shared logic — they cannot drift.
- [ ] The command responds within Slack's window despite reading multiple records (ack-then-post, like the `/control` report).
- [ ] The signal/ranking logic is tested via the moto `db` fixture (prior art: the burnout CSV tests); the command + manager gate are tested at the handler seam with the existing Slack fakes.

## Blocked by

None - can start immediately.
