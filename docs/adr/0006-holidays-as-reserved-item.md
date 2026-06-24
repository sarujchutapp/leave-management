# Store holidays as a reserved item, not a dedicated table

Company holidays live as a single reserved `__holidays__` item in the `employees`
table (a `{ "<iso date>": {label, calendar_event_id} }` map), read by a keyed
`GetItem` — the same pattern as `__policy__` and `__board__`. There is no
`leave_holidays` table.

This **supersedes** the earlier (non-ADR, implicit) choice to give holidays their
own year-partitioned table, which `leave/holidays.py` had described as "a single
Query, no scan, consistent with ADR-0001."

## Why

- **Holidays are company config, not a per-entity collection.** They're one small
  shared set (`CONTEXT.md`: "a single shared set, no per-country/per-region
  variation"), admin-maintained, read on nearly every request — much more like the
  central **policy** than like **requests**. Config-like singletons in this codebase
  already live as reserved items; modeling holidays the same way is consistent.
- **No new IAM / infra.** A dedicated table needs `dynamodb:CreateTable` on
  `leave_holidays`, which the deploy role lacks (it had been deferred for exactly
  this reason). The reserved item reuses the existing `GetItem`/`UpdateItem` grant on
  `leave_employees` — no admin permission ask, no second table to own.
- **Read path is equal-or-leaner.** Holiday lookups often span two years (the
  optimizer reads year + year+1; `continuous_absence_length` crosses year
  boundaries). One `GetItem` of the whole map serves every year in a single
  round-trip and is trivially cacheable; a per-year `Query` table needs one call per
  year. The hot day-counting/optimizer logic is unaffected either way — it operates
  on an in-memory `set[date]` built once per command, outside any loop.

## Considered alternatives

- **Dedicated `leave_holidays` table (PK year, SK date)** — the original design.
  Rejected for this use: its advantages (per-item writes, unbounded scale, table
  isolation) buy insurance against growth the domain rules out, at the cost of a
  permission ask and extra infra. Revisit if holidays ever stop being one shared set
  (per-office calendars, thousands of entries, richer per-holiday queries).

## Consequences

- Every `Scan` of the `employees` table must skip `__holidays__`, as it already
  skips `__policy__`/`__board__` (report builder's `RESERVED`, the carry-in
  recompute; the name/manager-keyed scans skip it for free since it has neither).
- One item holds all holidays → a 400 KB ceiling (thousands of dates; non-issue for
  a few dozen/year — old years can be pruned). Writes are a read-modify-write of the
  one item, fine at admin-edit frequency (setup + the odd change).
- Admins add/remove holidays from `/control` (Holidays modal); CSV seeding via
  `import_holidays.py` is unchanged. The `leave_holidays` table, its env var, and its
  entry in `terraform/operator-policy.json` are removed.
