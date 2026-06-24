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

---

## As-built (done)

- `leave/optimizer.py`: extracted the candidate generation into `_all_candidates`
  and added `top_breaks(..., limit=3)` — ranks all valid breaks longest-first
  (then least quota, then earliest) and greedily keeps distinct ones. Distinctness
  (`_distinct_options`): two options are kept apart only when their days-off spans
  differ on **more days than they share** — the days in exactly one span must
  outnumber the days in both (`lenA + lenB - 2*overlap > overlap`). So options may
  share a boundary weekend, but a break that mostly retraces another collapses to
  the better-ranked one. `longest_break` now delegates to `top_breaks(limit=1)`
  (kept + still tested for the single best).
- `_span_overlap_days` measures shared days-off calendar days between two breaks.
- `leave/handlers.py`: `_suggest_breaks` (top_breaks gather) + `_render_breaks`
  render a numbered, longest-first list in `/advance`; degrades to one line when
  only one distinct break exists, and to ADVANCE_NOTHING when none.
- Tests: `tests/test_optimizer.py` (distinct options, unique>shared invariant,
  the `_distinct_options` rule incl. its equal-days boundary, degrade-to-one,
  empty); `tests/test_advance.py` (multiple numbered options + every suggested
  break passes validate_request).

Decisions: distinctness is measured on the *days-off span* (not the booking), and
the rule is proportional — two options stay distinct only when their unique days
outnumber their shared days (replacing the original flat ">2 days" threshold, per
follow-up feedback). Equal unique/shared collapses. No new UI/interactive surface
(still a text reply); the Book button and group-break picker are later slices
(#41, #42).
