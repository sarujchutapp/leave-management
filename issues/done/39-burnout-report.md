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

---

## As-built (done)

- Pure measures in `leave/burnout.py` (no DB, no Slack), tested directly in
  `tests/test_burnout.py`:
  - `no_break_stretch(today, last_taken_end, next_booked_start)` — the rank key.
    Calendar days from the last *taken* (past approved) leave to the next *booked*
    (future approved/pending) leave. No past leave → anchor at year start (a defined
    start, not an error); nothing booked ahead → run to today.
  - `longest_working_stretch(start, end, leave_ranges, holidays)` — supporting flag.
    Longest run of working days (Mon-Fri, holidays excluded) that no leave interrupts;
    weekends/holidays span a run, a leave day resets it. Counted in working days.
- `build_burnout_csv(db, today)` in `leave/report.py` (alongside `build_report_csv` /
  `build_history_csv`): gathers each employee's taken/booked leave via the existing
  `_employee_requests` GSI helper, ranks by no-break stretch (longest first, name
  tie-break), and emits flags: remaining vacation, days left in year, longest working
  stretch. Tested via the moto `db` fixture (ranking + never-took-leave).
- Picker: third option "Team burnout risk" (`burnout`) added to `build_report_modal`;
  `initial_option` now selects by value (3 options). No person picker needed.
- Delivery: `submit_report_apply` gains a `burnout` branch reusing the existing
  `_dm_csv`. No `app.py` change — the report submit is wired generically.

Decisions: the working-stretch window is the whole calendar year (future
approved/pending breaks reset it), so the flag surfaces the longest *planned*
unbroken grind, not just the realized one. Half-days are treated as breaks (any
approved/pending leave). Both flags are plain numbers — no composite score.
