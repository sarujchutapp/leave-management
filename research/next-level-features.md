# Next-Level Features — Research & Design Brief

Status: **ideation complete, not yet specced.** This is the input for a future planning/PRD
session, written for the engineer who will implement it.

## Goal

Move the system beyond a normal CRUD leave tracker. Turn data we *already store* into
intelligence so a company prefers ours. The pitch:

> Our leave system doesn't just track time off — it **optimizes** it, **protects** your
> people, and shares the popular dates **fairly**.

## Design constraints (apply to every feature below)

1. **Deterministic only.** No LLM / natural-language parsing for now (reserved for a later
   "final version"). Every feature here is plain arithmetic/rules over existing data.
2. **Reuse existing data; avoid new models.** Notably: use the `manager_id` hierarchy instead
   of introducing explicit "teams."
3. **The acceptance filter:** a feature must compute something a human *won't or can't
   eyeball*. If a manager can glance at the calendar and get it, it's not a feature — it's the
   calendar with extra steps. (This is why several "dashboard" ideas were rejected; see below.)
4. **Slack-native, small teams (~5–20 people).**

## Existing data this builds on (current schema)

- **employees** (`slack_user_id` PK): `real_name`, `manager_id`, `allowances` (optional
  per-person override), `carry_in` (vacation, per year).
- **requests** (`request_id` PK; GSI `by_employee` = `employee_id` + `start_date`):
  `leave_type` (sick|vacation|personal), `start_date`, `end_date`, `half`
  (morning|afternoon|null), `status` (pending|approved|declined), `calendar_event_id`.
- **holidays** (`year` + `holiday_date`): `label`. *(NB: table not yet created in prod — see
  ADR-0003 / terraform note; day-counting degrades to "no holidays" if absent.)*
- **policy item** (`slack_user_id = __policy__`): `allowances`, `max_carry_over`, `max_total`,
  `consecutive_limit`.
- Day-counting rule: weekdays only; weekends + holidays don't consume quota. Half-day = 0.5.

---

# Pillar 1 — Optimize (Leave Optimizer)

The headline differentiator: genuine optimization no human does by hand. A suite of four jobs.

**1a. Longest-break maximizer**
- *What:* given remaining vacation + holidays, suggest which working days to spend to maximize
  *consecutive* days off (bridge days). e.g. "Take Mon+Tue → 5-day break for 2 days quota."
- *Inputs:* employee's remaining balance (derived), `holidays`, weekends, existing approved
  `requests` (don't suggest already-booked days).
- *Surface:* employee command (extends `/dayoff` flow or a new read-only command).

**1b. Expiring-quota warning**
- *What:* warn when a user holds vacation that won't carry past year-end (above
  `max_carry_over`, or non-carryover). Value is the **push**, not the math.
- *Inputs:* remaining vacation, `max_carry_over`/`max_total`, days left in year.
- *Surface:* proactive Slack DM (scheduled near year-end).

**1c. Whole-year plan**
- *What:* run the maximizer across the *whole* year — distribute the full budget across the
  year's best bridge opportunities. e.g. "Spend your 10 days → 4 long weekends + one 9-day
  break." Push in January.
- *Inputs:* full annual allowance, `holidays`, weekends.

**1d. Synchronized group break**
- *What:* user picks members to optimize *together*; find dates where the whole group can be
  off for the max collective consecutive break, given each member's remaining quota + existing
  bookings. e.g. "You + 2 teammates can all get a 5-day overlap the week of June 8."
- *Inputs:* selected members' balances + approved `requests`, `holidays`, weekends.
- *Note:* heaviest of the four (multi-person search). Build last within this pillar.

All four are deterministic and reuse existing quota/holiday/request data.

---

# Pillar 2 — Protect (Burnout Board)

Validated by market research: a competitor (**Timetastic**) leads its marketing with this, so
a *company* will buy it as a headline, not a footnote. Distinct selling point from Pillar 1.

- *What:* deterministic engine ranking the team by burnout risk, then nudging the at-risk
  person and/or their manager *before* it's a problem.
- *Signals (all plain arithmetic on existing data):*
  - days since last taken leave (per person),
  - whether anything is booked ahead,
  - remaining allowance vs. days left in year,
  - longest consecutive working stretch.
- *Inputs:* `requests` history + future, `allowances`/balance, `holidays`/weekends for the
  working-stretch calc, `manager_id` for routing the manager nudge.
- *Surface:* admin/manager view (rank list) + proactive DM nudges.
- *Why it passes the filter:* a calendar shows who's *off*; this surfaces who's *quietly never
  off* — requires correlating history + future + accrual across the team over time.

---

# Pillar 3 — Be Fair (Fair Allocation / holiday rotation)

White space — **no leave tool productizes this** (only appears as advice in HR guides). The
most ambitious pillar; a fair, transparent referee for over-subscribed popular dates.

- *What:* when a contested period (year-end, Songkran, pre-long-weekend Fridays) is
  over-subscribed, replace silent first-come-first-served with a transparent rule. Priority
  driven mainly by **who got that period off last year** (rotation), optionally
  advance-notice/seniority. e.g. "Alice had year-end off in 2025; Bob & Carol didn't →
  priority Carol → Bob → Alice."
- *Inputs:* multi-year `requests` history (who got which contested period), a capacity limit.
- *Surface:* engages at request/approval time for flagged contested periods.
- *Why it passes the filter:* needs multi-year memory applied consistently — a manager can't
  do this in their head, so they default to FCFS and breed resentment.

**Prerequisites — must exist before this is buildable (sequence last):**
- A notion of "contested" = a **coverage/capacity limit**. Today we only *warn* (Coverage
  Radar); this needs an actual enforced/known cap per contested period.
- **Multi-year history** to rotate on — nothing to rotate in year one.
- Socially delicate: a wrong rule feels *more* unfair than FCFS. Keep rules transparent.

---

# Supporting feature — Coverage Radar (manager-side)

Not a pillar, but kept. At approval time, warn the **manager** when too many of their direct
reports are out together. Uses `manager_id` (shared manager = de-facto team); no new "team"
model. Also a prerequisite stepping-stone toward Pillar 3's capacity concept.

---

# Suggested build order

1. **Pillar 1a/1b** (longest-break + expiring warning) — cheapest, strongest demo, pure
   extensions of existing math.
2. **Pillar 2** (Burnout Board) — second selling point; existing data, no new prerequisites.
3. **Pillar 1c/1d** (whole-year + group break) — deepen the optimizer.
4. **Coverage Radar** — useful on its own and seeds the capacity concept.
5. **Pillar 3** (Fair Allocation) — last; depends on a capacity limit + accumulated history.

---

# Parked (revisit later)

- **AI-native / natural-language** requests + conversational balance assistant — the "final
  version." Deliberately deterministic until then.
- **Reverse optimizer (goal → dates)** — "I want a 9-day trip in October" → min-quota date
  set. Strong, but leans natural-language; park with the AI-native work.
- **Conflict-aware suggestions for the whole team** — needs team/role grouping; too complex.

# Considered & rejected (with reason)

- **Carry-over-aware timing** — eyeball-able; fails the filter.
- **Capacity/blackout rules as a standalone, manager weekly digest, year-end forecast** —
  "calendar with extra steps"; re-present visible data. (Capacity *limit* still needed as a
  Pillar-3 prerequisite, but not as a standalone feature.)
- **Auto Slack status/DND, approver fallback, stale-request nudges** — conveniences /
  chore-automation, not "next level." Could revisit as polish.
- **Bus-factor / skill-coverage** — needs role/skill data we don't model; same complexity we
  rejected for teams.
- **Leave-liability $ engine** — needs salary data; enterprise/finance-oriented; off-target
  for small teams.

---

# Sources (market research, 2026)

- Timetastic — Burnout Board (Pillar 2 precedent):
  https://help.timetastic.co.uk/en/articles/13193421-the-burnout-board
- Timetastic — state of burnout 2025 / time-off data:
  https://timetastic.co.uk/blog/the-state-of-burnout-in-2025-and-how-time-off-data-can-help/
- Vacation Tracker — Max Users Away / coverage (Coverage Radar, commoditized basic form):
  https://vacationtracker.io/capability/leave-approval/
- Day Off — avoiding overlapping leave:
  https://day-off.app/how-to-avoid-overlapping-leave-requests/
- PeopleManagingPeople — 2026 benefit trends / fairness (Pillar 3 white space):
  https://peoplemanagingpeople.com/payroll-compensation/employee-benefit-trends/
- AIHR — 11 HR trends 2026:
  https://www.aihr.com/blog/hr-trends/
- Vacation Tracker — mandatory vacation policy:
  https://vacationtracker.io/blog/mandatory-vacation-policy/
- Visier — hidden costs of unused PTO (leave-liability, rejected):
  https://www.visier.com/blog/avoid-the-hidden-costs-of-unused-paid-time-off/
- Vacation Tracker — leave liabilities (rejected):
  https://vacationtracker.io/blog/leave-liabilities/
- Flamingo — features (table-stakes reference):
  https://flamingoapp.com/features/
