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
- **Provision (WSL):** `terraform init` (initializes the S3 backend) then `terraform apply` — the first apply imports the
  two existing DynamoDB tables and creates the Lambda, Function URL, IAM role, log group, and
  the SSM parameters (placeholder values).
- **Set secret values out-of-band:** `aws ssm put-parameter --overwrite` for the three
  parameters (`SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, and the Google JSON via
  `--value file://service-account.json`) — so the real values never enter Terraform state.
- **Slack dashboard (manual):** **disable Socket Mode**, set the **Request URL** (Event
  Subscriptions) and **Interactivity Request URL** to the Function URL (`terraform output`),
  and remove the app-level token.
- **Verify:** `smoke_check.py` PASS, then `/dayoff` end-to-end through the deployed Lambda.

## Acceptance criteria

- [ ] `terraform apply` imports the two tables and provisions the Lambda + least-privilege IAM role (no static AWS keys in prod)
- [ ] The three SSM SecureString values are set out-of-band; no secrets in Terraform state
- [ ] Function URL live; Slack app switched to HTTP mode (Request + Interactivity URLs set), app-level token removed
- [ ] `/dayoff` works end-to-end (submit → manager ticket → approve → calendar event) via the Lambda
- [ ] Idle cost confirmed ~$0 (scale-to-zero; no always-on compute)

## Blocked by

- #19 — SSM secrets bootstrap in the Lambda entrypoint
- #20 — Terraform module + WSL build script
