# Use DynamoDB for persistence

We replaced Postgres with AWS DynamoDB (on-demand / `PAY_PER_REQUEST` billing) for
true pay-per-usage cost at low and bursty volume (~5–20 users, expected ~$0/month on
the free tier).

This **reverses** the earlier "NoSQL considered and rejected" note in
`docs/design/leave-management-design.md`. That rejection's stated reasons no longer
hold against the actual code: the balance SUM is computed in app code (not SQL), and
no denormalized counters exist — balance is always derived from raw request rows. Every
access pattern is scoped to a single entity (by `slack_user_id` or `request_id`), so the
only relational-flavored query (date-overlap) is handled by fetching one employee's
handful of requests and filtering in Python.

## Shape

- Two tables: `employees` (PK `slack_user_id`) and `requests` (PK `request_id`, a
  `uuid4` hex string).
- `requests` carries a GSI `by_employee` (partition `employee_id`, sort `start_date`)
  serving the balance, overlap, and cancellable-list queries. Non-key predicates
  (`status`, `leave_type`, date-overlap) are filtered in app code.
- Dates stored as ISO `YYYY-MM-DD` strings (lexicographic order matches chronological);
  string↔`date` conversion is confined to `requests.py`.

## Considered alternatives

- **Stay on Postgres** — rejected for idle cost at low usage.
- **Google Firestore** — would reuse the existing GCP project + service account and is
  also pay-per-use; team preferred DynamoDB.
- **MongoDB Atlas** — its free tier is a fixed shared cluster, not pay-per-usage, so it
  doesn't match the cost goal.

## Consequences

- Adds AWS as a second cloud vendor (the project is otherwise all-Google via the Calendar
  service account); `SETUP.md` gains an AWS account + IAM step.
- boto3's resource API returns numbers as `Decimal`, so `allowances` values are
  deserialized back to `int` in `requests.py` to keep `Decimal` out of balance math and
  Slack messages.
- Status-transition guards remain read-then-write (the pre-existing, accepted race at this
  scale); a `ConditionExpression` is the cheap future hardening if needed.
