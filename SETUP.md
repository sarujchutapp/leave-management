# Setup

One-time provisioning of the three external resources, then a smoke check. All steps here are manual dashboard work; when done you fill in `.env` and run `python smoke_check.py`.

## 1. Slack app

1. Go to https://api.slack.com/apps → **Create New App** → From scratch. Pick your personal test workspace.
2. **Slash Commands** → Create New Command for each, any request URL placeholder (Socket Mode ignores it):
   - `/dayoff` — request leave
   - `/dayoff-cancel` — cancel a pending or upcoming-approved request
   - `/control` — admin control plane (gated by `SLACK_ADMIN_IDS`)
3. **Socket Mode** → toggle on. When prompted, generate an **App-Level Token** with scope `connections:write` → copy it (`xapp-...`) into `SLACK_APP_TOKEN`.
4. **Interactivity & Shortcuts** → toggle on (URL is ignored under Socket Mode).
5. **OAuth & Permissions** → Bot Token Scopes → add `chat:write` and `commands`. (Modals and DMs are covered by these.) Add `files:write` too if you use `/control` → Report, which uploads the usage CSV to the admin's DM.
6. **Install App** to the workspace → copy the **Bot User OAuth Token** (`xoxb-...`) into `SLACK_BOT_TOKEN`.

## 2. AWS DynamoDB

Persistence is DynamoDB in on-demand (pay-per-request) mode — see [ADR-0001](docs/adr/0001-dynamodb-for-persistence.md) for the rationale.

1. Create an AWS account at https://aws.amazon.com (the free tier covers this usage).
2. In the console → **IAM → Users → Create user**, then attach a DynamoDB-access policy (`AmazonDynamoDBFullAccess` is simplest for a personal setup; scope it down for a shared account).
3. Open the user → **Security credentials → Create access key** ("Application running outside AWS"). Copy the key id/secret into `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`, and set your region in `AWS_REGION` (e.g. `us-east-1`). The table names default to `leave_employees` / `leave_requests`; override `EMPLOYEES_TABLE` / `REQUESTS_TABLE` to use different ones.

## 3. Google Calendar + service account

1. With your **personal Gmail**, open Google Calendar → create a new calendar named **Team Leave**.
2. Go to https://console.cloud.google.com → create a project → **APIs & Services → Enable APIs** → enable **Google Calendar API**.
3. **APIs & Services → Credentials → Create credentials → Service account**. After creating, open it → **Keys → Add key → JSON** → download. Save it in this repo as `service-account.json` (gitignored). Note the service account's email (`...@...iam.gserviceaccount.com`).
4. Back in Google Calendar → Team Leave → **Settings and sharing → Share with specific people** → add the service account email with **"Make changes to events"**.
5. Same settings page → **Integrate calendar → Calendar ID** → copy into `TEAM_CALENDAR_ID`.

## 4. Configure and verify

1. `cp .env.example .env` and fill in every value.
2. `python -m venv .venv && .venv\Scripts\activate` (Windows PowerShell) then `pip install -r requirements.txt`.
3. `python -m leave.seed` — provisions both DynamoDB tables + the `by_employee` GSI (on-demand) and seeds proxy employees.
4. `python smoke_check.py` — expect `PASS` on all three. The calendar check creates and immediately deletes a throwaway event tomorrow.

## 5. Production deploy (HTTP mode on Lambda, via Terraform) — HITL

Provisioned with Terraform from WSL; remote state in S3, secrets in SSM SecureString. See
[ADR-0003](docs/adr/0003-terraform-deploy-ssm-secrets.md) for the rationale and the
`terraform/` module. These are the manual steps a human runs.

**Region:** resources run in **`ap-southeast-1`** (Singapore) — set in `terraform.tfvars`. The
state bucket lives in `ap-southeast-7` (created below). `ap-southeast-7` can't host the Lambda
because Function URLs aren't supported there yet.

**One-time — create the Terraform state bucket.** It backs the S3 backend and is *not*
managed by Terraform (chicken-and-egg). Run once per account, in `ap-southeast-7`:

```
aws s3api create-bucket --bucket your-tfstate-bucket \
  --region ap-southeast-7 --create-bucket-configuration LocationConstraint=ap-southeast-7
aws s3api put-bucket-versioning --bucket your-tfstate-bucket \
  --versioning-configuration Status=Enabled
aws s3api put-public-access-block --bucket your-tfstate-bucket \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket your-tfstate-bucket \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

Then the per-deploy steps:

1. **Build the artifact** (in WSL, so wheels are Linux/x86_64): `cd terraform && ./build.sh`.
2. **Provision** (in WSL): `terraform init` (initializes the S3 backend) then `terraform apply`.
   It creates the two DynamoDB tables, the Lambda, Function URL, IAM role, log group, and the
   SSM parameters (with placeholder values). (If the tables ever pre-exist — e.g. from #15 — run
   `terraform import aws_dynamodb_table.employees leave_employees` / `... .requests leave_requests`
   first so they're adopted, not recreated.)
3. **Set the secret values out-of-band** (not in Terraform state), in `ap-southeast-1`:
   ```
   aws ssm put-parameter --region ap-southeast-1 --overwrite --type SecureString --name /leave-bot/slack-bot-token        --value 'xoxb-...'
   aws ssm put-parameter --region ap-southeast-1 --overwrite --type SecureString --name /leave-bot/slack-signing-secret   --value '...'
   aws ssm put-parameter --region ap-southeast-1 --overwrite --type SecureString --name /leave-bot/google-service-account --value file://service-account.json
   ```
4. **Get the Function URL:** `terraform output function_url`.
5. **Reconfigure the Slack app** (https://api.slack.com/apps → your app). This bot uses **slash
   commands + interactivity only** — *not* the Events API, so leave **Event Subscriptions** off:
   - **Socket Mode** → toggle **off** (do this first — the URL fields stay greyed out otherwise).
   - **Interactivity & Shortcuts** → set the **Request URL** to the Function URL (carries modal
     submits + the approve/decline buttons).
   - **Slash Commands** → set the **Request URL** on both `/dayoff` and `/dayoff-cancel`.
   - **Basic Information → App-Level Tokens** → delete the `connections:write` token (HTTP mode uses `SLACK_SIGNING_SECRET`, not the app-level token).
6. **Verify:** `python smoke_check.py` (PASS on all three), then run `/dayoff` end-to-end
   (submit → manager ticket → approve → calendar event) through the deployed Lambda.

## Run modes

- **Local development — Socket Mode:** `python app.py`. Uses `SLACK_APP_TOKEN` and a persistent WebSocket; no public URL needed.
- **Production — HTTP mode on AWS Lambda:** `lambda_handler.handler` behind a Lambda Function URL, provisioned by Terraform. Needs `SLACK_SIGNING_SECRET` (not the app-level token) and is scale-to-zero. See §5 above; tracked in issue #17.
