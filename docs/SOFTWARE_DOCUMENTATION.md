# Leave Management — Software Documentation

|  |  |
|--|--|
| **Project** | Leave Management (Slack leave bot) |
| **Repository** | `github.com/sarujchutapp/leave-management` |
| **Status** | Feature-complete through V4; in production on AWS (see §11) |
| **Document type** | Technical / software design documentation (consolidated) |
| **Last updated** | 2026-07-02 |
| **Author** | Saruj Chutapornpong |

> This document is the single technical overview of the system. It stitches together the material that already lives in the repo — [`README.md`](../README.md) (operator-facing), [`CONTEXT.md`](../CONTEXT.md) (domain language), [`SETUP.md`](../SETUP.md) (runbook), and the ten ADRs under [`docs/adr/`](adr/) — and adds the parts that were only implicit in the commit history: the architecture as-built, the data model, the feature catalogue, the module reference, and the release-by-release development history.
>
> Where this document summarises a decision, the linked ADR remains the authority.

---

## 1. Introduction

### 1.1 Purpose

Requesting time off used to mean DMing your manager, who eyeballed a calendar, said yes, and recorded the leave by hand — often by editing a shared Excel sheet, screenshotting it, and dropping the image into a group chat. This project replaces that ritual with **one Slack slash command, one-click approval, and automatic bookkeeping**: balances, a shared team calendar, and a live leave board that the bot keeps current.

### 1.2 Scope

The system serves a **single small organisation** (\~5–20 employees, a handful of managers) running in **one Slack workspace**. It covers the full life-cycle of a leave request — request → approve/decline → land on calendar and board → cancel or early-return — plus per-type balance tracking, company holidays, vacation carry-over, a consecutive-absence cap, an in-Slack admin control plane, a deterministic leave optimizer, and burnout signals.

It deliberately does **not** attempt: employee self-registration, approval chains / backup approvers, a web UI, multi-workspace or multi-tenant operation, or any ML/LLM-driven recommendation (all suggestions are plain arithmetic).

### 1.3 Intended audience

Engineers maintaining or extending the bot, and operators deploying and running it. Readers new to the domain should read [`CONTEXT.md`](../CONTEXT.md) first — the vocabulary there (half day, carry-in, continuous absence, leave board, no-break stretch, …) is used throughout and not re-defined here.

### 1.4 Design principles

Four principles recur across every ADR and most commits, and explain why the code looks the way it does:

1. **Pay-per-use, scale-to-zero.** At this volume the whole stack should cost roughly **$0/month** when idle. This drove DynamoDB over Postgres (ADR-0001) and Lambda over an always-on host (ADR-0002).
2. **Derive, don't store.** Balances are computed live from raw request rows, not kept as counters. The only persisted balance figure is the per-person vacation `carry_in`, and only because it recurses into prior years (ADR-0004). A new holiday therefore retroactively refunds overlapping leave for free.
3. **Least privilege, then a deliberate exception.** V1/V2 gave the Lambda almost no database permissions; destructive work ran as a human with their own credentials. V3's admin control plane consciously reverses that for config operations, guarded by an application-level allowlist instead of IAM (ADR-0005).
4. **Vertical tracer-bullet slices.** Features ship as thin end-to-end slices (a happy path first, then guards and polish), each behind tests. The commit history reads as a sequence of these slices.

---

## 2. Product overview

### 2.1 Actors

| Actor | Who they are | What they can do |
|-------|--------------|------------------|
| **Employee** | Any seeded Slack user | Request leave (`/dayoff`), cancel or early-return their own leave (`/dayoff-cancel`), plan a break (`/advance`). |
| **Manager / approver** | An employee named as another's `manager_id` | Approve/decline reports' tickets; see a burnout board of their direct reports (`/burnout`). |
| **Top of chain** | An employee who is their own manager (or has none) | Their own requests **auto-approve** — no ticket routed. |
| **Admin** | A Slack user on the `SLACK_ADMIN_IDS` allowlist (currently exactly one) | Manage company config from Slack (`/control`): policy, carry-over, holidays, employees, reports, database clear. |

"Manager" and "Admin" are **orthogonal** — being one grants nothing of the other (CONTEXT.md). Employees are **pre-seeded**; there is no self-registration.

### 2.2 Slash commands

| Command | Actor | Purpose |
|---------|-------|---------|
| `/dayoff` | Employee | Open the request modal (type, dates, optional half, optional reason); shows remaining balance. |
| `/dayoff-cancel` | Employee | Cancel a pending/future request, or **early-return** an in-progress leave. |
| `/advance` | Employee | Leave Optimizer: longest break you can still take, top distinct options, and a shareable group-break window. Book straight from the result. |
| `/burnout` | Manager | Direct reports ranked by burnout risk (no-break stretch), with remaining vacation, next booked break, an expiring-quota flag, and a Nudge button. |
| `/control` | Admin | The admin control plane — a menu of modals for policy, carry-over, holidays, employees, reports, and clear. |

### 2.3 Surfaces the bot maintains

- **Slack** — the whole request/approve/admin experience lives in modals, DMs, and Approve/Decline buttons. No public channel is required for the core flow.
- **Google Calendar** — a shared "Team Leave" calendar. Approved leave becomes an all-day event tinted with the requester's stable per-person colour; cancelling removes it. Holidays are mirrored as all-day events (display only, never the counting source).
- **Leave board** — a Google Sheet rendered as a _people × days_ grid coloured by leave type, rebuilt on every approve/cancel. The bot posts an "updated :clipboard: link" message to a dedicated Slack channel. Opt-in via `LEAVE_BOARD_CHANNEL` + `LEAVE_SHEET_ID`.

---

## 3. System architecture

### 3.1 Component view

```
                    ┌─────────────────────────────────────────┐
   Slack workspace  │  Slash commands · modals · buttons · DMs │
   (one workspace)  └───────────────┬─────────────────────────┘
                                     │  signed HTTPS (prod) / WebSocket (dev)
                     ┌───────────────▼───────────────┐
                     │  Bolt app  (build_app factory) │
                     │  app.py / lambda_handler.py    │
                     └───────────────┬───────────────┘
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         │                           │                           │
  ┌──────▼──────┐            ┌───────▼────────┐          ┌────────▼────────┐
  │  leave/*    │            │  DynamoDB      │          │  Google APIs    │
  │  domain     │──reads/────▶  employees     │          │  Calendar +     │
  │  logic      │  writes    │  leave_requests│          │  Sheets         │
  │             │            │  (holidays*)   │          │  (service acct) │
  └─────────────┘            └────────────────┘          └─────────────────┘
                                                          * holidays deferred in prod
```

The **Bolt app factory** `build_app(calendar=None, faas=False)` (in `app.py`) is the single seam that both run modes share. Handlers are registered as **plain functions** in `leave/handlers.py` so tests can call them with fakes; on Lambda the slow submit/approve/ cancel work runs as **lazy (post-ack) listeners** so Slack's 3-second acknowledgement window is never missed.

### 3.2 Run modes (ADR-0002)

|  | Local development | Production |
|--|-------------------|------------|
| Transport | Slack **Socket Mode** (WebSocket, no public URL) | Slack **HTTP mode** behind a **Lambda Function URL** |
| Entrypoint | `python app.py` (uses `SLACK_APP_TOKEN`) | `lambda_handler.handler` (uses `SLACK_SIGNING_SECRET`) |
| Authenticator | App token | Slack request signature |
| Lifecycle | Always-on local process | **Scale-to-zero** Lambda |

The same code, tests, and handlers run in both modes; only the transport and the secret used to authenticate differ.

### 3.3 Cold start and keep-warm (ADR-0007)

Because `/dayoff` opens a modal, it must respond **synchronously** within Slack's timeout — a cold Lambda could miss it. Two mitigations, layered:

1. **Cold-path trimming** — lazy Google imports, batched SSM fetches, a single balance query, and 1024 MB of memory for CPU headroom (a series of commits on 2026-06-12).
2. **Keep-warm ping** — a scheduled EventBridge rule pings the Lambda every **4 minutes**, around the clock, with `{"warmup": true}`. The handler primes the SSM secrets and builds the Bolt app, then returns before the Slack path. 4 minutes (not 5) buys margin against Lambda's fuzzy idle-reclaim lower bound.

> **Operational note:** the keep-warm EventBridge resources are currently **commented out** in Terraform — the deploy role lacks the EventBridge permissions to create them (see the `keep-warm-deploy-blocked` memory and the README notes). The cold-path trimming is live; the scheduled ping is not.

---

## 4. Technology stack

| Layer | Choice | Notes |
|-------|--------|-------|
| Language | **Python 3.12** |  |
| Slack SDK | **`slack-bolt`** | Socket Mode (dev) + HTTP mode (prod) from one factory. |
| Compute | **AWS Lambda** + Function URL | Scale-to-zero (ADR-0002). |
| Storage | **AWS DynamoDB**, on-demand (`PAY_PER_REQUEST`) | ADR-0001. |
| Calendar / board | **Google Calendar API** + **Google Sheets API** | Via a service account. |
| Secrets | **AWS SSM Parameter Store** SecureString | Fetched on cold start (ADR-0003). |
| IaC | **Terraform** (flat root module, S3 remote state) | ADR-0003. |
| Tests | **pytest** + **moto** | Fully offline — no real AWS/Slack/Google. |
| Region | **`ap-southeast-1`** (Singapore) | State bucket in `ap-southeast-7`. |

---

## 5. Data model

All state lives in **two DynamoDB tables** (a third, `leave_holidays`, is deferred in production — see §12).

### 5.1 `employees`

Partition key `slack_user_id`. Stores the person's `real_name`, `manager_id` (nullable → top of chain / auto-approve), and an optional per-type `allowances` map (an **override** of the central policy, e.g. for a part-timer). It also holds the stored per-person vacation `carry_in` by year.

Company-wide configuration is kept as **reserved items in this same table**, read by a keyed `GetItem` — the same pattern for each:

| Reserved key | Holds |
|--------------|-------|
| `__policy__` | The central leave policy: per type — base allowance, max carry over, max total, consecutive limit; plus the leave-year reset date. |
| `__board__` | Denormalised leave-board state. |
| `__holidays__` | Company holidays as `{ "<iso date>": {label, calendar_event_id} }` (ADR-0006). |

### 5.2 `leave_requests`

Partition key `request_id` (`uuid4`). Fields: `employee_id`, `leave_type` (`sick`/`vacation`/`personal`), `start_date`, `end_date` (ISO `YYYY-MM-DD`), an optional **half** (`morning`/`afternoon`), `status` (`pending`/`approved`/`declined`/`cancelled`), `reason`, `decline_reason`, `calendar_event_id`, manager-ticket refs, and timestamps. Full history is kept — nothing is hard-deleted in the normal flow. A GSI `by_employee` (partition `employee_id`, sort `start_date`) serves per-employee queries.

### 5.3 The balance model (ADR-0004)

Balances are **derived live**, not stored:

```
remaining[type] = available[type] − used-this-period[type]
used            = Σ working days of the employee's pending + approved requests this period
available(vac)  = min(base_allowance + carry_in, max_total)
carry_in[Y]     = min(leftover[Y−1], max_carry_over)     ← the ONE persisted balance figure
```

Working-day counting (`leave/balance.py`) skips weekends and holidays and charges a half day as `0.5`. Because `used` is recomputed from raw rows, adding a holiday retroactively refunds any leave that overlapped it. Sick and personal reset to their fresh allowance each period; only vacation carries over. `carry_in` is persisted because it recurses into every prior year — computing it live would mean walking an employee's whole history each time.

> **Pending reserves quota (ADR-0010).** The hard submit-time gate subtracts _pending as well as approved_ leave, so two overlapping in-flight requests can't both pass the balance check. This superseded the earlier approved-only rule (ADR-0008).

### 5.4 The leave year (ADR-0004 + issues #56– #58)

The leave year is **not hard-wired to 1 January**. A configurable, forward-only **reset date** in the central policy defines the current leave _period_; balances, the optimizer, reports, and nudges all re-base on that period rather than the calendar year.

---

## 6. Feature specification

Grouped by the four "pillars" the QA pass uses (`QA.md`): `/dayoff`, `/advance`, `/control`, `/burnout`.

### 6.1 Request & approval (`/dayoff`, `/dayoff-cancel`)

- **Request modal** — leave type, native date pickers (Buddhist-era dates from the picker are converted), an optional half-day selector (single date only), an optional reason, and the requester's current remaining balance shown inline.
- **Validation** (`leave/validation.py`) — a hard gate at submit: `end ≥ start`, no backdating, sufficient quota (pending + approved counted, ADR-0010), no overlap with the requester's own requests, half-day rules, at least one working day (weekend/holiday-only requests are rejected), and the **consecutive-absence limit** (a vacation request may not create a continuous absence longer than the cap — default 15 calendar days; weekends, holidays, and leave of any type fill the run).
- **Routing** — a valid request either **auto-approves** (top of chain) or DMs an Approve/Decline ticket to the mapped manager, carrying context (employee, type, dates, reason, remaining balance, and the Coverage Radar warning — §6.3).
- **Decision** — Approve creates the calendar event and rebuilds the board; Decline offers an optional reason. Both notify the employee. Stale tickets (already-decided or now-invalid requests) are guarded and withdrawn rather than crashing.
- **Cancel / early return** — a pending or future request is fully **cancelled** (calendar event removed, board updated, manager FYI'd). An **in-progress** leave is instead **early-returned**: days already taken through today stay consumed; only the untaken remainder is refunded and cleared (ADR-0009 territory; CONTEXT.md "Early return").

### 6.2 Company configuration & day-counting

- **Half days** — a `0.5`-day leave on a single date, always a named morning or afternoon half, so coverage is precise.
- **Holidays** — a company-wide set (no per-region variation) stored as a reserved item (ADR-0006), ingested from an operator CSV or pasted/imported via `/control`, and mirrored onto the calendar for display. Removing a holiday is scoped to today-onward.
- **Central leave policy** — base allowance + the two carry caps + consecutive limit, in one place; an admin edits it from Slack across two modals (leave-limits and carry-over).
- **Carry-over** — vacation only, governed by `max carry over` (what rolls out) and `max total` (in-year availability); a cap of zero disables it.

### 6.3 Leave Optimizer (`/advance`) — ADR-0008/0010

Deterministic suggestions from data the system already holds — plain arithmetic, no LLM:

- **Longest-break finder** — the longest single continuous absence you can still take this period given remaining vacation, bounded by the consecutive limit.
- **Top distinct options** — 2–3 meaningfully different break windows (a proportional distinctness rule keeps them from clustering).
- **Group-break finder** — for a chosen set of people, the longest window they can _all_ be off at once, each within their own balance and cap — revealing only the shared window, never anyone's balance.
- **Book / Book-mine** — commit a suggestion straight from the result. The optimizer plans against _free_ days (pending + approved subtracted); the validator is the hard gate.

### 6.4 Coverage Radar (`/dayoff` approval ticket) — issue #38

A **soft** heads-up on the manager's approval ticket when another of their direct reports already has overlapping leave (approved _or_ pending). It surfaces conflicts a glance at the board would miss, because pending leave isn't on the board. It is a warning the manager weighs, never a block.

### 6.5 Burnout signals (`/burnout`, `/control` report) — issues #39, #45– #47

Built on the **no-break stretch** — calendar days since a person's last _taken_ leave (backward-looking). A break booked ahead is relief, not endured time: it never inflates the stretch and it lowers risk.

- **Burnout board** (`/burnout`, manager) — a ranked modal, one card per report: stretch, remaining vacation, next booked break, an **expiring-quota** flag, and a **Nudge** button that sends a supportive bot DM to the at-risk report.
- **Burnout report** (`/control`, admin) — the fuller CSV with extra flags (days left in the period, long consecutive-working stretch). Every flag is explainable — a reason, never an opaque score.

### 6.6 Admin control plane (`/control`) — ADR-0005, issues #30– #35, #49– #51

An admin-only menu of modals: **View settings**, **Leave limits**, **Carry-over** (with the forward-only reset-date picker), **Holidays** (add/remove/import), **Manage employees** (add/edit/delete with a required-manager guard and in-flight-leave settlement, ADR-0009), **Report** (all-employee quota CSV _or_ one person's history), and **Clear** (a typed-confirm wipe of requests/calendar/board that keeps employees + policy). Every submit closes the modal and DMs the admin a result.

---

## 7. Module reference

Application code lives in the `leave/` package plus the two entrypoints. Sizes are a rough guide to where the weight sits (≈5,500 lines total).

| Module | Lines | Responsibility |
|--------|------:|----------------|
| `app.py` | 495 | Bolt `build_app` factory (shared by both modes) + Socket-Mode dev entrypoint. |
| `lambda_handler.py` | 71 | Production Lambda handler: SSM secrets on cold start, keep-warm short-circuit, Google key to `/tmp`. |
| `leave/handlers.py` | 1651 | All Slack handler logic as plain functions (open/submit/approve/decline/cancel/control/advance/burnout). |
| `leave/blocks.py` | 1138 | Block Kit builders — every modal, the approval ticket, decision notices. |
| `leave/requests.py` | 615 | Request persistence, derived balances, lazy carry-in, continuous-absence calc. |
| `leave/report.py` | 210 | Report CSV builders (quota + per-person history). |
| `leave/optimizer.py` | 198 | The deterministic Leave Optimizer (longest-break, options, group-break). |
| `leave/holidays.py` | 160 | Holidays store + CSV/paste apply + the day-counting queries; degrades gracefully if unprovisioned. |
| `leave/seed.py` | 120 | Provision tables + seed central policy and proxy employees (tests + first setup). |
| `leave/board.py` | 118 | Leave-board state + Google-Sheet render + Slack link post. |
| `leave/policy.py` | 107 | Central policy as a reserved item; allowance resolution with per-employee override. |
| `leave/leave_year.py` | 101 | Leave-year calendar seam + configurable reset date. |
| `leave/sheets_client.py` | 100 | Thin Google Sheets wrapper; renders the grid. |
| `leave/db.py` | 85 | DynamoDB handle (employees/requests/holidays) + employee lookup + whole-table iterator. |
| `leave/calendar_client.py` | 64 | Thin Google Calendar wrapper; per-person event colours. |
| `leave/validation.py` | 62 | The hard submit-time gate (dates, overlap, balance, half-day, consecutive limit). |
| `leave/view_state.py` | 50 | One envelope reader for Slack view-submission state. |
| `leave/absence.py` | 47 | The pure continuous-absence kernel. |
| `leave/coverage.py` | 46 | Coverage Radar peer-overlap computation. |
| `leave/burnout.py` | 45 | No-break-stretch / burnout signal computation. |
| `leave/carryover.py` | 30 | Pure carry-over roll-forward math. |
| `leave/balance.py` | 28 | Working-day counting (weekdays, holiday-aware, half-day 0.5). |

The small pure modules (`absence`, `carryover`, `balance`, `coverage`, `burnout`, `view_state`) are the product of a late refactoring pass (§9, V4) that extracted decision kernels out of `handlers.py`/`requests.py` so they can be unit-tested in isolation.

### 7.1 Operational scripts

Run **as yourself** (your own AWS creds — the deploy role has no item permissions), venv active, targeting `ap-southeast-1`:

| Script | Purpose |
|--------|---------|
| `smoke_check.py` | Health check across Slack, Calendar, DynamoDB (expect `PASS`). |
| `python -m leave.seed` | Provision tables + seed policy and proxy employees. |
| `add_employees.py` | Seed/edit the real employees. |
| `import_holidays.py` | Apply a holidays CSV + mirror all-day calendar events. |
| `recompute_carry.py` | Rebuild a stored `carry_in` after a closed year is edited. |
| `clear_requests.py` | Empty requests, delete their calendar events, reset the board. |
| `clear_calendar.py` | Delete orphaned calendar events not tracked by any row. |

---

## 8. Design decisions (ADR index)

Decisions are recorded as ADRs under [`docs/adr/`](adr/). In short:

| ADR | Decision | Relationship |
|-----|----------|--------------|
| [0001](adr/0001-dynamodb-for-persistence.md) | DynamoDB (on-demand) for persistence | Reverses the design doc's "NoSQL rejected" note. |
| [0002](adr/0002-aws-lambda-http-mode.md) | Run on Lambda in Slack HTTP mode; Socket Mode for dev | Extends 0001 from storage to compute. |
| [0003](adr/0003-terraform-deploy-ssm-secrets.md) | Provision with Terraform; secrets in SSM SecureString | Resolves the open question in 0002. |
| [0004](adr/0004-carry-over-balance-model.md) | Central policy + per-person stored `carry_in` | Handles what breaks 0001's derive-everything model. |
| [0005](adr/0005-admin-control-plane-in-slack.md) | App-level admin authz over IAM least-privilege | Consciously reverses the V1/V2 least-privilege boundary. |
| [0006](adr/0006-holidays-as-reserved-item.md) | Holidays as a reserved `__holidays__` item | Supersedes the implicit "holidays table" choice. |
| [0007](adr/0007-keep-warm-ping.md) | Scheduled keep-warm ping (4 min) | Refines 0002. |
| [0008](adr/0008-optimizer-plans-against-free-days.md) | Optimizer plans against free days; validator approved-only | **Superseded by 0010.** |
| [0009](adr/0009-mutating-employee-settles-in-flight-leave.md) | Mutating an employee settles their in-flight leave | Fixes orphaned tickets/events on delete/re-org/clear. |
| [0010](adr/0010-pending-leave-reserves-quota.md) | Pending leave reserves quota | Supersedes 0008; validator now subtracts pending too. |

---

## 9. Development history

The project ran from **2026-06-05** to **2026-07-02** in four version arcs. Each feature was built as a vertical tracer-bullet slice on its own branch and merged to `main`; issue numbers below refer to the GitLab tracker (`issues/done/` holds the in-repo copies).

### V1 — MVP (2026-06-05 → 06-12)

Grilling session and design doc first (`docs/design/`), then eight numbered **slices** built the core loop end-to-end: external-resource setup + smoke check → app skeleton + `/dayoff` modal → DB schema + seed → submit/persist → manager approval → auto-approve → Google Calendar event → cancel. A run of quality-of-life fixes followed (rename `/leave`→`/dayoff`, Buddhist-era date conversion, cancel-flow iterations, stale-ticket guards, optional end date).

The stack was then **migrated to production shape**: a 5-part DynamoDB migration (#11– #14, ADR-0001), a Lambda HTTP-mode entrypoint with lazy listeners (#16, ADR-0002), and a Terraform deploy with SSM secrets and S3 remote state (#17– #20, ADR-0003). The live deploy closed on 06-12, followed by the first round of cold-start reduction.

### V2 — leave model (2026-06-16 → 06-18)

Driven by `V2_requirement.md`. A second grilling session produced `CONTEXT.md` and the carry-over ADR (0004). Then, largely in one day, the six model features landed (#22– #28): half-days, central leave policy, holiday-aware day-counting + holidays store, holiday CSV import + calendar mirror, vacation carry-over (lazy carry-in), consecutive-absence limit, and the shared leave board. Holidays were **deferred in production** (graceful "no holidays" degrade) because the deploy role couldn't create the table. The board moved from a Block Kit grid to a rendered Google Sheet, per-person calendar colours were added, and the README was brought up to V2.

### V3 — admin control plane (2026-06-18 → 06-21)

Driven by `V3_requirement.md` and ADR-0005. The `/control` command grew slice by slice (#30– #35): admin gate + menu + View Settings, the leave-limits modal, the carry-over modal with recompute-all, the typed-confirm Clear, the all-employee Report CSV, and Manage Employees (add/edit/delete). Follow-up fixes hardened it: `upsert_employee` patches instead of full-row replace, Report DMs via `chat:write`, Clear wipes DB before best-effort calendar cleanup, the `BatchWriteItem` grant for Clear, and reject-zero-working-day requests.

### V4 — next-level features, hardening & refactor (2026-06-23 → 07-02)

Driven by `research/next-level-features.md` (PRD #36) and later research briefs. This arc added the **Leave Optimizer** (`/advance`, slices #37/ #40/ #41/ #42/ #43 — longest break, distinct options, Book, group-break, Book-mine), **Coverage Radar** (#38), and the **burnout** suite (#39, #45– #47 — report, board, expiring-quota flag, Nudge). Operational work included the keep-warm ping (ADR-0007) and its later parking, and the coldstart write-up.

The arc closed with a **QA + hardening + refactoring** push (late June → 02 July):

- **Correctness:** settle in-flight leave on delete/re-org/clear (ADR-0009), policy sanity invariants + ability to disable carry-over / consecutive limit, recompute carry-in on allowance change, a sweep of QA edge-case bugs across all four pillars, holiday-import add/remove/import + all-or-nothing validation (#49– #51), and **early return** for in-progress leave (#53/ #54).
- **The configurable leave year** (#56– #58): a leave-year calendar seam with a forward-only reset date, with `/advance`, reports, and nudges re-based on the current period.
- **Concurrency & scale:** harden concurrency and remove Slack's 100-option ceilings.
- **Refactoring for testability** — the most recent commits extracted pure kernels out of the big handler/request modules: the continuous-absence kernel (`absence.py`), a single whole-table employee iterator (`db.py`), the carry-over roll-forward (`carryover.py`), and one Slack view-submission envelope reader (`view_state.py`).

---

## 10. Testing strategy

Tests are **fully offline** on [`moto`](https://github.com/getmoto/moto) — no real AWS, Slack, or Google is touched — so `pytest` runs anywhere:

```bash
pip install -r requirements.txt
pytest
```

Handlers are plain functions that accept injected fakes (`tests/fakes.py`), which keeps the Slack/Google boundaries mockable without a live workspace. Coverage mirrors the module map — there is a dedicated test file per feature area (`test_advance.py`, `test_burnout*.py`, `test_carryover*.py`, `test_consecutive.py`, `test_control.py`, `test_coverage.py`, `test_halfday.py`, `test_holiday*.py`, `test_leave_year.py`, `test_optimizer.py`, `test_view_state.py`, and the core `test_handlers.py`/`test_validation.py`/`test_requests.py`, among others). The `QA.md` pass drove an explicit adversarial sweep of the four pillars whose findings became the late-June bug-fix commits.

---

## 11. Deployment & infrastructure

The full runbook is [`SETUP.md`](../SETUP.md). In outline:

1. **External resources** — a Slack app, an AWS account, and a Google service account + shared calendar (SETUP §1–3).
2. **Local dev** — copy `.env.example` → `.env`, create the venv, `python -m leave.seed`, `python smoke_check.py` (expect PASS), then `python app.py` over Socket Mode.
3. **Production** — from WSL: `terraform/build.sh` (builds the Linux/x86_64 Lambda zip), `terraform apply`, set the SSM secrets, then point the Slack app at the Function URL. Everything runs in **`ap-southeast-1`**.

Terraform owns AWS infrastructure only — the Lambda, its Function URL, a least-privilege IAM role, the DynamoDB tables, and (when unblocked) the keep-warm EventBridge rule. The **deploy role has no DynamoDB item permissions**; all data operations run as a human operator with their own credentials (drop the role creds first: `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN`).

---

## 12. Security & authorization

- **Production authenticator** — Slack's request signature (verified via `SLACK_SIGNING_SECRET`); the Function URL is otherwise public but signature-gated.
- **Admin authz** — an application-level allowlist of Slack member IDs (`SLACK_ADMIN_IDS`), checked in the handler, gates every `/control` operation (ADR-0005). This is deliberately _not_ IAM: the Lambda role holds the DynamoDB permissions the admin operations need, and the Slack-user check is the actual guard.
- **Least privilege elsewhere** — the deploy role manages infrastructure only; the runtime role holds exactly the item permissions the bot needs and nothing more.
- **Secrets** — Slack and Google credentials live in SSM SecureString, fetched on cold start; the Google service-account key is written to `/tmp` at runtime, never bundled in the repo.

---

## 13. Known limitations & deferred scope

- **Holidays deferred in production** — the `leave_holidays` table isn't created (the deploy role lacks `CreateTable` on it), so day-counting runs in a graceful "no holidays" mode. To enable: widen the deploy role for `leave_holidays`, restore the table + `HolidaysRead` IAM blocks in `terraform/main.tf`, `terraform apply`, then run `import_holidays.py`. (Holiday _config_ via `/control` already stores to the reserved `__holidays__` item — ADR-0006 — independent of the table.)
- **Keep-warm parked** — the EventBridge ping is committed but commented out pending an admin granting the deploy role EventBridge permissions. Cold-path trimming is live; the scheduled ping is not.
- **Single workspace** — the bot serves whichever workspace its configured token belongs to; moving workspaces means updating the SSM token/secret.
- **No self-registration / approval chains / web UI / multi-tenant** — out of scope by design (§1.2).
- **Further ideas** are captured in [`research/`](../research/) — `deferred-scope.md`, `next-level-features.md`, and `slack-surfaces-and-app-home.md` (a possible Slack App Home command-center).

---

## 14. Reference map

| Need | Read |
|------|------|
| Operator/user overview | [`README.md`](../README.md) |
| Domain vocabulary (authoritative) | [`CONTEXT.md`](../CONTEXT.md) |
| Setup & deploy runbook | [`SETUP.md`](../SETUP.md) |
| Original V1 design | [`docs/design/leave-management-design.md`](design/leave-management-design.md) |
| Why a decision was made | [`docs/adr/`](adr/) |
| What a feature's slice covered | [`issues/done/`](../issues/done/) |
| Future ideas | [`research/`](../research/) |

