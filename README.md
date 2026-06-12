# leave-management

A Slack bot for requesting and approving employee leave. Employees run `/dayoff` to
request time off, managers approve or decline from a Slack message, and approved leave
lands on a shared Google Calendar. Balances are tracked per leave type (sick / vacation /
personal).

Runs **scale-to-zero** on AWS Lambda (Slack HTTP mode) behind a Function URL, with
DynamoDB for storage — roughly **$0/month** at low usage.

## How it works

- **Slack** — slash commands (`/dayoff`, `/dayoff-cancel`) plus interactive modals and
  Approve/Decline buttons. Everything happens in bot DMs (no public channel).
- **AWS Lambda (HTTP mode)** behind a **Function URL** is the production entrypoint;
  Slack's request signature is the authenticator. Local development uses Slack
  **Socket Mode** instead.
- **DynamoDB** (on-demand) stores employees and leave requests.
- **Google Calendar** — an approved request creates an all-day event on a shared team
  calendar; cancelling an approved request removes it.

Key decisions are recorded in [`docs/adr/`](docs/adr/):
- **ADR-0001** — DynamoDB for persistence
- **ADR-0002** — run on AWS Lambda in Slack HTTP mode
- **ADR-0003** — provision with Terraform; secrets in SSM SecureString

## Setup

The full step-by-step runbook is **[SETUP.md](SETUP.md)**. In short:

1. **Create the three external resources** — a Slack app, an AWS account, and a Google
   service account + shared calendar (SETUP §1–3).
2. **Local dev** — copy `.env.example` → `.env` and fill it in, then:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   python -m leave.seed        # provision tables + seed proxy employees
   python smoke_check.py       # expect PASS on Slack, Calendar, DynamoDB
   python app.py               # run locally over Socket Mode
   ```
3. **Production** — deploy with Terraform from WSL (SETUP §5): `terraform/build.sh`,
   `terraform apply`, set the SSM secrets, then point the Slack app at the Function URL.
   Resources run in **`ap-southeast-1`**.

## Repository layout

### Application
| Path | What it is |
|------|-----------|
| `app.py` | Bolt app factory (`build_app`) shared by both run modes, plus the **Socket Mode** entrypoint for local dev (`python app.py`). |
| `lambda_handler.py` | **Production** entrypoint — the AWS Lambda `handler` (Slack HTTP mode). Fetches secrets from SSM on cold start and writes the Google key to `/tmp`. |
| `leave/handlers.py` | Slack handler logic (open / submit / approve / decline / cancel) as plain functions, so tests can pass fakes. |
| `leave/blocks.py` | Block Kit builders for the modals, the manager approval ticket, and decision notices. |
| `leave/validation.py` | Request validation — dates, overlap, and remaining balance. |
| `leave/balance.py` | Weekday counting used for balances. |
| `leave/requests.py` | Leave-request persistence (DynamoDB) and the derived-balance query. |
| `leave/db.py` | DynamoDB connection handle + employee lookup. |
| `leave/calendar_client.py` | Thin wrapper over the Google Calendar API. |
| `leave/seed.py` | Provision the tables (used by tests and initial setup) and seed **proxy** employees. |

### Infrastructure & docs
| Path | What it is |
|------|-----------|
| `terraform/` | The production stack as code — Lambda, Function URL, least-privilege IAM, SSM SecureString params, DynamoDB tables. State in S3. See ADR-0003. |
| `terraform/build.sh` | Builds the Lambda zip **in WSL** (Linux/x86_64 wheels). Run before `terraform apply`. |
| `SETUP.md` | One-time external-resource setup + the production deploy runbook. |
| `docs/adr/` | Architecture decision records. |
| `issues/` | In-repo copies of the tracker issues (`done/` for completed). |

### Operations / utilities
Run these **as yourself** (your own AWS credentials, which have DynamoDB/Calendar
access — *not* the deploy role), with the venv active. They target `ap-southeast-1`.

| Script | What it does |
|--------|-------------|
| `python smoke_check.py` | Health check across Slack, Google Calendar, and DynamoDB. Expect `PASS`. |
| `python -m leave.seed` | Provision the tables and seed the **proxy** test employees. |
| `add_employees.py` | Seed / edit the **real** employees (member id + manager). Copy from `add_employees.example.py`. |
| `clear_requests.py` | Reset: empty `leave_requests` **and** delete the calendar events those approvals created. Keeps employees. |
| `clear_calendar.py` | Delete calendar events **not** tracked by any DynamoDB row (orphaned / old events); keeps the ones still linked to a request. |

> The deploy role manages **infrastructure only** — it has no DynamoDB item permissions.
> Run the data scripts above as your own user (drop the role creds first:
> `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN`).

## Run modes
- **Local development — Socket Mode:** `python app.py` (uses `SLACK_APP_TOKEN`; no public URL).
- **Production — HTTP mode on Lambda:** `lambda_handler.handler` behind the Function URL,
  provisioned by Terraform (uses `SLACK_SIGNING_SECRET`). Scale-to-zero.

## Tests
Fully offline on [`moto`](https://github.com/getmoto/moto) — no real AWS, Slack, or Google:
```bash
pip install -r requirements.txt
pytest
```

## Notes
- **Region:** the production stack runs in **`ap-southeast-1`** (Singapore); the Terraform
  state bucket is in `ap-southeast-7`. `ap-southeast-7` can't host Lambda Function URLs yet
  (see ADR-0003).
- **One workspace at a time:** the bot serves whichever Slack workspace the configured bot
  token belongs to. Pointing it at another workspace means updating the SSM token/secret.
