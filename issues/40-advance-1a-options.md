# 1a: top 2-3 distinct break options

- Issue: #40
- Labels: ready-for-agent

---

## Parent

V4 PRD: #36

## What to build

Enrich the longest-break finder to return the **top 2–3 distinct options** instead of
a single break, so the caller can choose between different parts of the year.

The optimizer returns up to three options ranked longest-first (tie-break least
quota, then earliest), made distinct by collapsing candidates that overlap by more
than 2 days (keep the longer, then the cheaper); a 1–2 day overlap is allowed, so two
options may share a boundary weekend without being treated as duplicates. `/advance`
renders the 2–3 options, each with its dates, cost, and resulting span.

## Acceptance criteria

- [ ] `/advance` shows up to 3 break options, longest-first.
- [ ] Options are genuinely distinct — no two are framings of the same break (overlap > 2 days collapses to the better one; ≤ 2 days is allowed).
- [ ] Each option independently respects the live consecutive limit and the caller's remaining balance, and lists dates + cost + span.
- [ ] If only one (or zero) distinct break exists, the command degrades gracefully to that.
- [ ] The distinctness/ranking rule is covered by pure-function tests over hand-built inputs.

## Blocked by

- 1a longest-break tracer: #37
