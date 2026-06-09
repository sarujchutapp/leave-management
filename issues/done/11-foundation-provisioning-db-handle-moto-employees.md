# DynamoDB migration 1/5: foundation — provisioning, db handle, moto fixture, employees path

> **Issue:** #11  
> **Labels:** AFK

---

## Parent

#10 — Migrate persistence from Postgres to DynamoDB (pay-per-usage)

## What to build

The foundational tracer bullet that proves the DynamoDB stack end-to-end through the employees read path. Introduce the boto3-based persistence handle and offline test backend, provision both tables, and make employee lookup work against DynamoDB.

- `db.connect()` returns a small handle holding the two boto3 Table resources (`employees`, `requests`) plus the `by_employee` GSI name — threaded everywhere the old SQL connection went. Rename the threaded `conn` parameter to `db` across `leave/` and `tests/`.
- `seed.py` grows a `create_tables()` that provisions BOTH tables on-demand (`PAY_PER_REQUEST`): `employees` (PK `slack_user_id`) and `requests` (PK `request_id`) with the `by_employee` GSI (partition `employee_id`, sort `start_date`, projection ALL). This replaces `apply_schema`. Employee seeding uses `put_item`.
- The `conn` fixture in `conftest.py` becomes a `moto` (`mock_aws`) backed `db` handle that creates both tables + GSI per test — fully offline, no AWS account or Docker.
- `get_employee` reads via `GetItem`; `manager_id = None` round-trips as a DynamoDB NULL and back.
- Add `boto3` and `moto[dynamodb]` to dependencies.

This is the blocker for all other slices: it establishes the handle, provisioning, and the test fixture every later slice relies on.

## Acceptance criteria

- [ ] `db.connect()` returns a handle exposing the `employees` and `requests` Table resources and the GSI name
- [ ] `seed.create_tables()` provisions both tables + the `by_employee` GSI in on-demand mode
- [ ] `python -m leave.seed` provisions and seeds proxy employees end-to-end
- [ ] The threaded parameter is renamed `conn` → `db` throughout `leave/` and `tests/`
- [ ] The test fixture is moto-backed and creates tables + GSI per test (no Postgres, no `DATABASE_URL`)
- [ ] `test_db.py` passes on moto, including null-manager preservation
- [ ] `get_employee` returns `None` for an absent user and the full attributes (incl. `allowances`) for a present one

## Blocked by

- None - can start immediately