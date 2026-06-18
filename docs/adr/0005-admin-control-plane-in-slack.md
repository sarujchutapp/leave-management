# Admin control plane in Slack: app-level authz over IAM least-privilege

V3 adds an admin-only `/control` command so a non-technical admin can manage the company
configuration (leave policy, carry-over caps, the leave board, employees, reports) from
Slack instead of running scripts. This **reverses a deliberate V1/V2 boundary**: until now
the Lambda execution role had almost no item permissions (read an employee, read/write a
request — no `Scan`, no `DeleteItem`, no policy `PutItem`), and every destructive or
config-changing operation ran as a *human* using *their own* AWS credentials (the data
scripts: `clear_requests.py`, `add_employees.py`, `recompute_carry.py`, …). The deploy
role manages infrastructure only and has no item permissions at all. We decided to move
those operations into the bot, guarded by an **application-level admin check** (the Slack
user id must be on an allowlist) rather than by IAM.

## The decision

- **Authorization is an allowlist of Slack member IDs** (`SLACK_ADMIN_IDS`, currently one
  — the owner), checked at the top of the `/control` handler *and* on each sub-modal
  submit. A non-secret value, set as a Lambda env var via Terraform. This — not IAM — is
  now the only thing gating destructive and config-changing actions.
- **The Lambda execution role widens** to cover what the admin actions need: `employees`
  gains `PutItem`/`DeleteItem`/`Scan`; `requests` gains `Scan`/`DeleteItem`. (Holiday
  management is **out of V3** — see below — so no holiday IAM or table change ships.)
- **Destructive actions carry in-app friction.** Clear requires the admin to type a
  confirmation word in the modal; employee delete is blocked when the person is still
  someone's manager. IAM no longer makes these impossible, so the guardrails move into the
  handler.
- **The operator scripts stay.** `/control` is additive; the scripts remain the
  break-glass path (and the only way to do anything the bot still can't, e.g. create
  tables). They run as a human with their own creds, exactly as before.

## Considered alternatives

- **Keep everything as human-run scripts (status quo).** Smallest blast radius — the bot
  literally cannot wipe data — but it is precisely the "you have to touch code / run AWS
  scripts" friction V3 exists to remove. Rejected for the stated goal.
- **Per-action IAM instead of one app check.** Genuine least-privilege, but Slack has no
  way to assume different AWS roles per button; the Lambda has one execution role, so the
  permissions it needs for *any* admin action are available to *every* code path. An
  app-level check is the only enforcement point that actually varies per user.
- **A separate admin Lambda with its own broad role.** Isolates the wide permissions from
  the hot request path, but doubles the deploy surface (second function, URL, secrets) on a
  scale-to-zero stack for a single-admin tool. Not worth it at this size; revisit if the
  admin surface grows.

## Consequences

- **Bigger blast radius.** The bot can now scan and delete all requests and rewrite policy
  and employees. The protection is a string check on the Slack user id plus Slack request
  signing — if the signing secret leaks or the admin check has a bug, the damage is far
  larger than under the old IAM-as-guard model. This is the accepted trade: admin
  convenience for a wider failure mode, mitigated by the single-entry allowlist and the
  typed-confirm / manager-guard friction.
- **Some admin actions are slow** (full-table scans, per-employee carry-in recompute, CSV
  upload). On Lambda they must run as **lazy listeners (post-ack)**, like approve/cancel,
  to stay inside Slack's 3s ack window.
- **Holiday management is deferred with the holidays table.** Set-Holiday needs the
  `leave_holidays` table, which still cannot be created (the deploy role lacks
  `dynamodb:CreateTable` on it — see the note in `terraform/main.tf` and ADR-0003). Until
  that prerequisite is resolved, `/control` ships without holiday editing; the rest of the
  admin surface does not depend on it.
