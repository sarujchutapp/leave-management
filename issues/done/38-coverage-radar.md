# Coverage Radar: peer-overlap warning on the approval ticket

- Issue: #38
- Labels: ready-for-agent

---

## Parent

V4 PRD: #36

## What to build

**Coverage Radar**: a warning line attached to the manager's existing approval
ticket when one or more of the requester's direct-report peers already have leave
overlapping the requested dates.

End-to-end: a pure function that takes the requested range and peers' leave intervals
(with status) and returns the peak per-day count of overlapping peers plus the
contributors; a thin gather of peers (employees sharing the requester's `manager_id`,
excluding the requester, via a filtered `Scan`); and injection of the warning into
the ticket built at submit time (`submit_leave_apply` / `build_ticket`).

It counts both approved and pending peer leave, labelled distinctly. Trigger: warn
when the peak count ≥ 1; attach nothing when zero. The warning shows names + the peak
day + status (approved/pending), but **not** leave type, and never blocks approval —
it is a heads-up the manager weighs. Computed once at submit (static on the ticket).

## Acceptance criteria

- [ ] When a request overlaps ≥1 peer's approved or pending leave, the manager's ticket includes a warning naming the peak day, the overlapping peers, and each one's status.
- [ ] Approved and pending overlaps are visually distinguished.
- [ ] When no peer overlaps, the ticket carries no warning line.
- [ ] The warning never shows the leave type of any peer.
- [ ] The warning never blocks or changes the approve/decline decision.
- [ ] A top-of-chain requester (auto-approve, no ticket) and a manager whose only report is the requester both produce no warning.
- [ ] The overlap core is a pure function tested directly (peer intervals + range → peak count + contributors, approved vs pending); ticket injection is tested at the handler seam with the existing Slack fake.

## Blocked by

None - can start immediately.

---

## As-built (done)

- Pure core `leave/coverage.py` (no DB, no Slack), tested directly in
  `tests/test_coverage.py`:
  - `peer_overlap(start, end, peers) -> PeerOverlap | None`. `peers` are
    (name, start, end, status) tuples; returns the busiest overlapping day
    (`peak_day`), how many peers are off then (`count`), and the (name, status)
    `contributors` on that day. Ties on count resolve to the earliest day; None
    when no peer overlaps the range.
  - `format_coverage_warning(overlap) -> str`. Renders the ticket line: peak day,
    count, and each peer by name + status with distinct markers (✅ approved,
    ⏳ pending). Never receives or shows the leave type.
- Gather + injection in `leave/handlers.py` (`_coverage_warning`): peers via the
  existing `list_reports(db, manager_id)` filtered Scan (requester excluded), each
  peer's pending/approved leave via the new `requests.pending_approved_intervals`.
  Computed once in `submit_leave_apply` and passed to `build_ticket`.
- `build_ticket` gains an optional `coverage_warning` param → a heads-up section
  above the Approve/Decline buttons; the buttons (decision) are untouched.

Decisions: half-day peer leave counts as an overlap (it still reduces coverage).
Top-of-chain requesters auto-approve and build no ticket, so they never warn; a
manager whose only report is the requester yields no peers → no warning. The
warning is static (computed at submit), per the issue.
