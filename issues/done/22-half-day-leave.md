# Half-day leave

- Tracker: #22
- Labels: AFK, ready-for-agent

## Parent

#21 — PRD: Leave Management V2

## What to build

Let an employee take a half day on a single date. On the leave request modal, when the request is a single day (start == end), the employee can mark it as a **morning half** or **afternoon half**. A half day consumes exactly `0.5` of balance.

End-to-end behavior:
- The request modal shows a half-day control that only applies to single-day requests; the submission captures which half (morning/afternoon).
- Day-counting returns `0.5` for a half-day request (and whole numbers otherwise).
- Balances, remaining, and any value that can now be fractional are kept as `Decimal` inside the requests/balance layer and rendered with `.5` in Slack strings.
- Overlap stays **date-granular**: a date already touched by any request (full or half) blocks another request on that date. Two half-days on one date are not allowed — switching half→full is done via cancel + rebook.
- The approved-leave calendar event stays all-day, with the half noted in the title (e.g. "Alice — vacation (morning)").

## Acceptance criteria

- [ ] A single-day request can be submitted as morning or afternoon half and persists which half it is.
- [ ] A half-day deducts exactly `0.5` from the relevant balance; balances display `.5` correctly in Slack.
- [ ] A half-day cannot be requested across a multi-day range (the control only applies when start == end).
- [ ] A second request on a date already used by any request (full or half) is blocked by the existing overlap rule.
- [ ] The calendar event for an approved half-day is all-day and its title indicates the half.
- [ ] Existing V1 behavior (whole-day requests, validations, auto-approve, cancel) is unchanged — no regression.
- [ ] Tests cover half-day submit, fractional balance, the single-day-only constraint, and date-granular overlap, asserting external behavior only (persisted rows, FakeCalendar, FakeSlackClient, validation dicts).

## Blocked by

- None - can start immediately

## Done (2026-06-16)

Implemented via TDD; all acceptance criteria met. Full suite 59 passed, no regressions.

- [x] Single-day request submits as morning/afternoon half and persists `half` (`None`/`"morning"`/`"afternoon"`).
- [x] Half-day deducts exactly `0.5`; balances render correctly (see note on representation).
- [x] Half-day across a multi-day range is rejected with an inline validation error.
- [x] A date already touched by any request stays blocked by the existing date-granular overlap rule (unchanged).
- [x] Approved half-day calendar event is all-day with the half in the title (e.g. "Alice — vacation (morning)").
- [x] No regression to whole-day requests, validations, auto-approve, cancel.
- [x] Tests assert external behavior only (persisted rows, FakeCalendar, FakeSlackClient, validation dicts).

**Key decisions / deviations:**
- **No `Decimal` storage.** Day counts stay *derived*, not persisted — the only new stored field is the `half` enum. Balances are computed as Python numbers: whole balances remain `int` (e.g. `10`), and a half makes the total a `float` (e.g. `9.5`), which renders cleanly with no `.0` artifact. So the PRD's "store fractional as Decimal" was unnecessary for this slice.
- **New `request_days(start, end, half)`** in `balance.py` wraps `count_weekdays`; a half on a working weekday = `0.5`, a half on a non-working day = `0` (forward-compatible with "holiday beats half" in #24). `count_weekdays` left pure/unchanged.
- **Modal selector always shown.** Slack input blocks can't be conditionally hidden by another field's value, so the half-day select is always present (default "Full day") and the single-day-only rule is enforced in validation.

**Notes for next iterations:** #24 (holiday counting) should extend `request_days`/`count_weekdays` to skip holidays and make a half on a holiday cost `0`. #28 (leave board) needs the persisted `half` for morning/afternoon glyphs.
