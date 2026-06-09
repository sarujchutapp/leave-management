# DynamoDB migration 2/5: request data-access layer (requests.py rewrite)

> **Issue:** #12  
> **Labels:** AFK

---

## Parent

#10 — Migrate persistence from Postgres to DynamoDB (pay-per-usage)

## What to build

Rewrite the request data-access layer (`requests.py`) against DynamoDB, preserving every function signature and return shape so the rest of the codebase is unaffected. This slice owns all request persistence, the GSI-backed derived queries, and the storage-detail boundary.

- `create_request` generates a `uuid4` hex `request_id` in app code and `put_item`s a pending request; `get_request` is a `GetItem` by `request_id`.
- The three GSI-backed read paths each `Query` the `by_employee` index by `employee_id`, then filter in application code (no server-side `FilterExpression`):
  - balance (`approved_weekdays_this_year` / `remaining_balance`) — query with a `start_date` sort-key range for the calendar year, then filter `status='approved'` and `leave_type`, reusing `count_weekdays`.
  - overlap (`has_overlap`) — query by employee, filter status + date-overlap.
  - cancellable-list (`cancellable_requests`, `can_cancel`) — query by employee, filter status + start-date rule, ordered by start date.
- Status mutations and setters (`approve_request`, `decline_request`, `cancel_request`, `set_calendar_event_id`, `set_ticket_ref`) are `UpdateItem`s; status guards stay read-then-write (no `ConditionExpression`).
- **Storage boundary lives here:** dates serialize to ISO `YYYY-MM-DD` on write and back to `date` on read; `created_at`/`updated_at` are app-set ISO strings; `allowances`/numeric values are deserialized from `Decimal` to `int` so `Decimal` never leaks out of this module.
- Rewrite the raw-SQL setup lines in `test_requests.py`/`test_balance.py` (e.g. `conn.execute("UPDATE requests SET status='approved'...")`) to go through the data-access functions.

## Acceptance criteria

- [ ] `create_request` returns a `uuid4` string id and persists a pending request; `get_request` fetches it by id
- [ ] Balance derivation matches prior behavior, incl. calendar-year boundary (other-year approved requests don't count)
- [ ] Overlap detection considers pending + approved and ignores cancelled
- [ ] Cancellable-list returns pending requests and approved-not-yet-started, ordered by start date
- [ ] Status mutations and the calendar/ticket setters update the persisted item
- [ ] No `Decimal` and no ISO date strings escape `requests.py` (callers receive `int`/`date`)
- [ ] `test_requests.py` and `test_balance.py` pass on moto, with raw-SQL setup rewritten onto the function seam

## Blocked by

- #11