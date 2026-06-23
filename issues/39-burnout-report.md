# Burnout report: no-break-stretch ranking in /control

- Issue: #39
- Labels: ready-for-agent

---

## Parent

V4 PRD: #36

## What to build

A **burnout report**: a third report type in the admin's `/control` report picker,
alongside the existing all-employee quota report and per-person history report.

End-to-end: a pure `db → CSV` builder (alongside `build_report_csv` /
`build_history_csv`) that ranks the team by **no-break stretch**, plus the report
picker option and the existing DM-the-CSV delivery.

The **no-break stretch** is computed by a pure helper: days since the employee's last
*taken* (past approved) leave, extended by whether and when they have anything booked
ahead (future approved/pending). The report ranks employees by this stretch (longest
first) and includes the supporting flags: remaining allowance vs. days left in the
year, and longest consecutive working stretch. Explainable — flags, never a single
composite score.

## Acceptance criteria

- [ ] `/control`'s report picker offers a third "burnout" option.
- [ ] Selecting it DMs the admin a report ranking employees by no-break stretch, longest first.
- [ ] Each row shows the no-break stretch and the supporting flags (remaining allowance vs. days-left, longest consecutive working stretch) — enough to see *why* a person ranks where they do.
- [ ] An employee who has never taken leave is handled sensibly (stretch measured from a defined start, not an error).
- [ ] The no-break-stretch helper is a pure function tested directly; the CSV builder is tested via the moto `db` fixture (prior art: the existing report CSV functions), asserting ranking and flags.

## Blocked by

None - can start immediately.
