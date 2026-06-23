# Leave Management

A Slack bot for requesting and approving employee leave. Employees request time off,
managers approve, approved leave lands on a shared team view, and balances are tracked
per leave type.

## Language

**Half day**:
A leave of `0.5` days taken on a single date (start == end). Always one of two named
halves — **morning half** or **afternoon half** — so coverage can be tracked and
visualized precisely. Both halves count as exactly `0.5` for quota. A half day cannot
be requested across a multi-day range.
_Avoid_: half-day leave, 0.5-day

**Holiday**:
A company-wide non-working date that does not consume leave quota. A single shared set
(no per-country/per-region variation), self-maintained — including company-internal
closures no public calendar lists. Each holiday is a date plus a label. A weekday that
is a holiday is skipped when counting the days a request consumes. Source of truth is the
`holidays` store, ingested from an operator-maintained CSV; the same source is mirrored
onto the Team Leave calendar as all-day events (a display mirror, not the counting source).
_Avoid_: public holiday, bank holiday, day off

**Carry-over**:
Unused leave from one year made available in the next. Applies to **vacation only**;
sick and personal reset to their fresh allowance each year. Governed by two
company-wide caps (same for everyone). No mid-year expiry — once carried in, a day is
indistinguishable from fresh allowance for the whole year.
_Avoid_: rollover, accrual

**Carry-in**:
The concrete number of days carried into a given year for a single employee:
`carry_in[Y] = min(leftover[Y-1], max carry over)`. Inherently per-person (it depends on
that individual's unused days). It is the one balance figure that is persisted; everything
else within the current year stays derived live.

**Admin**:
A single Slack user authorized to manage company-wide configuration (leave policy,
holidays, etc.) from Slack, without touching code. Identified by an allowlist of Slack
member IDs (currently exactly one). Distinct from a **manager/approver**, which is a
per-employee relationship for approving leave — being an admin grants no approval role
and vice versa.
_Avoid_: owner, superuser, top of chain

**Leave policy**:
The company-wide configuration that governs balances, kept in one central place (not
copied onto each employee): per leave type, the **base allowance**, **max carry over**,
**max total**, and the **consecutive limit**. Changing policy is a single edit — by an
**Admin** from Slack, or in code. The Slack editor splits the knobs across two modals:
*leave limits* (base allowance per type + consecutive limit) and *carry-over* (max carry
over + max total).

**Allowance**:
The fresh annual grant of a leave type. The **base allowance** comes from the central
leave policy; an employee may carry a personal *override* only as an exception (e.g. a
part-timer).

**Continuous absence**:
A maximal unbroken run of consecutive calendar days an employee does not work. Every
non-working day fills the run — leave of *any* type, weekends, and holidays — bounded on
each side by a day actually worked (a weekday that is neither holiday nor leave).

**Consecutive limit**:
The cap on the length of a continuous absence, currently **15 calendar days, vacation
only**. Enforced only when a vacation request is filed (a new request may not create a
continuous absence longer than the cap); sick/personal stretches are not themselves
capped but do count toward the run. A hard validation block, like the balance and overlap
checks.
_Avoid_: max leave, consecutive days off

**Leave board**:
A single shared month grid (people × days) posted in a dedicated Slack channel that the
bot keeps current, replacing the old "fill an Excel sheet, screenshot it, drop it in the
group chat" ritual. One authoritative message everyone looks at — not a per-person
command. Distinct from the Google Calendar (which remains the write-only event feed).
_Avoid_: calendar, dashboard, roster

**Leave Optimizer**:
Deterministic leave suggestions derived from data the system already stores
(remaining balance, holidays, weekends, existing requests) — plain arithmetic, no
LLM. Employees reach it through the `/advance` command. Its first job is the
**longest-break finder**: the longest single continuous absence a person can still
take in the current calendar year given their remaining vacation, bounded by the
consecutive limit. A second job, the **group-break finder**, takes a chosen set of
people and finds the longest window they can *all* be off at once — each within
their own balance and cap — revealing only the shared window, never anyone's
balance. Distinct from the proactive year-end nudges and the approval-time
referees, which fire on their own triggers, not from `/advance`.
_Avoid_: AI, recommender, planner

**Coverage Radar**:
A soft heads-up shown to a manager on a leave request's approval ticket when one
or more of their other direct reports (employees sharing the same manager) already
have leave — approved *or* still pending — overlapping the requested dates. It
surfaces overlap a glance at the leave board can miss, since pending requests
aren't on the board. A warning the manager weighs, never a block. The seed of a
later enforced capacity cap.
_Avoid_: conflict checker, blackout, capacity limit

**No-break stretch**:
How long a person has gone without time off — days since their last *taken*
(past approved) leave, extended by whether and when they have anything booked
ahead. The primary measure of **burnout risk**, ranked across the team
(longest first) with supporting flags (low remaining allowance late in the year,
a long consecutive working stretch). Surfaced as a **burnout report** the admin
pulls from `/control`; a future proactive **burnout warning** DMs the at-risk
person and/or their manager. Explainable by design — every flag says why, never
an opaque score.
_Avoid_: burnout score, wellness index

**Max carry over**:
The cap on how many unused days may roll *out* of a year into the next.

**Max total**:
The cap on how much vacation is *available within a year*: `min(allowance + carry_in,
max total)`.
