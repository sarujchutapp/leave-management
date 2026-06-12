# Deploy to AWS Lambda + Function URL and switch Slack to HTTP mode

> **Issue:** #17  
> **Labels:** HITL

---

## Parent

PRD: #18 — Deploy the leave bot to AWS Lambda via Terraform (HTTP-mode cutover)

## Context

The scale-to-zero deploy that removes idle hosting cost — the **HITL cutover slice** of
PRD #18. The AFK build work lands first: the SSM secrets bootstrap in `lambda_handler.py`
(#19) and the Terraform module + WSL build script (#20). This slice runs the live deploy
and cutover, which can't be done AFK: a human runs the build/apply from WSL, sets the
secret values out-of-band, reconfigures the Slack app dashboard, and verifies against the
live workspace. See ADR-0003 for the rationale.

## What to build

- **One-time — create the Terraform state bucket (S3 backend):** create `your-tfstate-bucket` in `ap-southeast-7` (versioning on, public access blocked, SSE-S3) — not managed by Terraform. See SETUP.md §5.
- **Build the artifact (WSL):** run `terraform/build.sh` so the zip is built with Linux/x86_64 wheels.
- **Provision (WSL):** `terraform init` (initializes the S3 backend) then `terraform apply` — creates
  the two DynamoDB tables, the Lambda, Function URL, IAM role, log group, and the SSM parameters
  (placeholder values). Resources run in `ap-southeast-1` (Function URLs aren't supported in
  `ap-southeast-7`). #15 was never run, so the tables didn't pre-exist; if they ever do,
  `terraform import` them first so they're adopted, not recreated.
- **Function URL public access:** the auth-`NONE` URL needs **both** `lambda:InvokeFunctionUrl`
  **and** `lambda:InvokeFunction` granted to `*` (AWS requirement since ~Oct 2025); the module
  includes both. Without the second, the URL returns `403` before the function runs.
- **Set secret values out-of-band** (in `ap-southeast-1`): `aws ssm put-parameter --overwrite` for
  the three parameters (`SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, and the Google JSON via
  `--value file://service-account.json`) — so the real values never enter Terraform state.
- **Slack dashboard (manual):** **disable Socket Mode**, set the **Interactivity** Request URL and
  the **Slash Command** URLs (`/dayoff`, `/dayoff-cancel`) to the Function URL (`terraform output`),
  and remove the app-level token. This bot uses slash commands + interactivity only — *not* Event
  Subscriptions.
- **Verify:** `smoke_check.py` PASS, then `/dayoff` end-to-end through the deployed Lambda.

## Acceptance criteria

- [ ] `terraform apply` creates the two tables and provisions the Lambda + least-privilege IAM role (no static AWS keys in prod)
- [ ] The three SSM SecureString values are set out-of-band; no secrets in Terraform state
- [ ] Function URL live; Slack app switched to HTTP mode (Request + Interactivity URLs set), app-level token removed
- [ ] `/dayoff` works end-to-end (submit → manager ticket → approve → calendar event) via the Lambda
- [ ] Idle cost confirmed ~$0 (scale-to-zero; no always-on compute)

## Blocked by

- #19 — SSM secrets bootstrap in the Lambda entrypoint
- #20 — Terraform module + WSL build script
