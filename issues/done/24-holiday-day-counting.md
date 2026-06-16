# Holiday-aware day-counting + holidays store

- Tracker: #24
- Labels: AFK, ready-for-agent

## Parent

#21 — PRD: Leave Management V2

## What to build

Make leave day-counting holiday-aware, backed by a new `holidays` store. A weekday that is a company **holiday** does not consume quota. Because balance is recomputed live from raw rows, a newly-added holiday automatically lowers the cost of already-approved leave that overlaps it (retroactive refund). A holiday always **beats** a half-day — a half on a holiday costs 0.

End-to-end behavior:
- A `holidays` store (mirrors the `requests`/`db` pattern) keyed by date, with a label and a `calendar_event_id` slot, plus a programmatic upsert. A moto table is provisioned in the test `db` fixture.
- Day-counting is extended to take the relevant holiday set and skip any weekday in it; balance and validation reflect this.
- Retroactive: adding a holiday reduces the counted cost of an overlapping approved request on next recompute.
- Holiday beats half-day: a half-day on a holiday date contributes 0.

This slice delivers the system-side quota effect; the operator CSV import and calendar mirror are a separate slice.

## Acceptance criteria

- [ ] A `holidays` store exists with a programmatic upsert and a moto table in the test fixture.
- [ ] A weekday holiday contributes 0 to the counted days of a request spanning it; weekends remain free as before.
- [ ] Adding a holiday that overlaps an already-approved request lowers that request's counted cost on the next balance computation (retroactive).
- [ ] A half-day falling on a holiday costs 0 (holiday wins).
- [ ] Non-holiday day-counting (including half-days) is unchanged — no regression.
- [ ] Tests cover holiday-skipping in `count_weekdays` (pure), through `remaining_balance`/`validate_request`, the retroactive case, and holiday-beats-half, asserting external behavior only.

## Blocked by

- #22 (Half-day leave) — day-counting is extended on top of fractional/half-day counting, and "holiday beats half" is built here.

## Done (2026-06-16)

Implemented via TDD; all acceptance criteria met. Full suite 71 passed, no regressions.

- [x] `holidays` store with a programmatic upsert; moto table provisioned in the `db` fixture (via `seed.create_tables`).
- [x] A weekday holiday contributes 0 to a request's counted days; weekends still free.
- [x] Retroactive: adding a holiday that overlaps an approved request lowers its cost on next recompute (live derivation, nothing stored).
- [x] Half-day on a holiday costs 0 (holiday beats half) — falls out of threading holidays through `count_weekdays`.
- [x] No regression to non-holiday counting / half-days.
- [x] Tests cover pure `count_weekdays` skipping, store query-by-year, retroactive refund through `remaining_balance`, holiday-beats-half, and holiday-aware `validate_request`.

**Key decisions / deviations:**
- **No table scan (honors ADR-0001).** The issue said "keyed by date"; I partitioned the `holidays` table by **`year`** (sort key `holiday_date`) so a year's holidays come from a single Query. `holidays_for_year` (balance summations, year-scoped) and `holidays_between` (validation, the request's own range) build the holiday set; callers pass it into `count_weekdays(start, end, holidays)` / `request_days(..., holidays)`.
- **`db.Db` gained a third table** (`holidays`); `connect()` and `create_tables` provision it; the moto `db` fixture gets it for free.
- **Holiday read adds one Query** to the balance path (summations) and one-or-two to validation. Not cached (kept simple); warm-instance caching is a future optimization if needed.

**⚠️ Infra not apply-verified.** Terraform changes were written (new `holidays` table, a read-only `HolidaysRead` IAM statement granting `GetItem`/`Query` only, the `HOLIDAYS_TABLE` Lambda env var, and a `holidays_table` variable) mirroring the `requests` patterns. `terraform fmt -check` and `terraform validate` both pass, but I could not run `terraform apply` in this environment — **a human must review and apply** before deploy. The Lambda needs read-only on holidays; operators write rows as themselves (the #25 import script), matching ADR-0003's "deploy role manages infra, data scripts run as the human."

**Notes for next iterations:** #25 (CSV import + calendar mirror) writes via `upsert_holiday` (the `calendar_event_id` slot is already on the row) and runs as the operator. #27 (consecutive limit) will reuse `holidays_between` when filling the absence run.
