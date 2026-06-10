# PRD: Deploy the leave bot to AWS Lambda via Terraform (HTTP-mode cutover)

> **Issue:** #18  
> **Labels:** ready-for-agent

---

## Problem Statement

As the maintainer, I want to stand up and re-deploy the production leave bot reproducibly, but today the only documented production path is manual AWS console/CLI work (issue #17 as originally written). Hand-clicking the Lambda, IAM role, Function URL, and environment is not reproducible, not reviewable, and easy to misconfigure. Separately, the bot's secrets — the Slack bot token, the Slack signing secret, and the Google service-account **private key** — have no defined home for a function that is reachable from the public internet through a Function URL, and I don't want any of them sitting in plaintext.

## Solution

Provision the entire AWS footprint with **Terraform** (a single flat root module under `terraform/`, S3 remote state), build the Lambda zip in **WSL** (so wheels are Linux/x86_64), and keep every secret in **AWS SSM Parameter Store SecureString**, fetched on cold start. The production deploy then becomes `build.sh && terraform apply` plus a short, documented checklist (set the SSM values out-of-band, reconfigure the Slack app, verify). The stack stays scale-to-zero at ~$0 idle. Rationale and the full decision set are recorded in [ADR-0003](docs/adr/0003-terraform-deploy-ssm-secrets.md); this extends ADR-0002 (run on Lambda in HTTP mode) and the code entrypoint from #16. End-user behaviour (the `/dayoff` and `/dayoff-cancel` flows) is unchanged.

## User Stories

1. As the maintainer, I want the Lambda, its IAM role, the Function URL, the SSM parameters, the log group, and the DynamoDB tables defined as Terraform code, so that the production deploy is reproducible and reviewable instead of a sequence of console clicks.
2. As the maintainer, I want Terraform to **adopt the two existing DynamoDB tables via `terraform import`** rather than recreate them, so that the live data seeded in #15 is preserved.
3. As the maintainer, I want one tool (Terraform) to own production infrastructure while `seed.create_tables()` stays as the moto-test provisioner, so that there is a single source of truth for prod and no drift between two provisioning paths.
4. As the maintainer, I want employee data seeding to remain a separate Python step (`python -m leave.seed`), so that infrastructure and data concerns stay separate.
5. As the maintainer, I want the Lambda packaged as a zip built in WSL, so that any compiled wheels match the Amazon Linux x86_64 runtime and the function actually imports at runtime.
6. As the maintainer, I want `boto3`, `moto`, and `pytest` excluded from the artifact, so that the zip stays small and free of test-only dependencies.
7. As the maintainer, I want the build step (`terraform/build.sh`) decoupled from `terraform apply` and both run from WSL, so that the artifact is built explicitly and debuggably rather than via a fragile `null_resource` hook.
8. As the maintainer, I want the Slack bot token, signing secret, and Google service-account JSON stored as SSM SecureString parameters, so that no secret — especially the RSA private key — ever sits in plaintext in Terraform state or in the deployment artifact.
9. As the maintainer, I want the Lambda to fetch those secrets on cold start and populate `SLACK_BOT_TOKEN`/`SLACK_SIGNING_SECRET` into the environment before the Bolt app is built, so that `build_app()` is unchanged.
10. As the maintainer, I want the fetched Google JSON written to `/tmp/service-account.json` with `GOOGLE_SERVICE_ACCOUNT_FILE` pointing there, so that `CalendarClient.from_env()` (which reads a file path) needs no change.
11. As the maintainer, I want the SSM parameters declared in Terraform with `lifecycle { ignore_changes = [value] }` and a placeholder value, so that their shape lives in code while the real values are set out-of-band and never enter state.
12. As the maintainer, I want to set the real secret values once after `apply` via `aws ssm put-parameter --overwrite`, so that rotating a secret is a single CLI call and not a code change.
13. As the maintainer, I want the Lambda's IAM role scoped to least privilege — `GetItem` on `employees`; `GetItem`/`PutItem`/`UpdateItem`/`Query` on `requests` and `Query` on the `by_employee` GSI; `ssm:GetParameter*` on the parameter path; `kms:Decrypt` only via SSM; `lambda:InvokeFunction` on its own ARN; and basic-execution logging — so that an internet-reachable function can do nothing beyond what the code requires.
14. As the maintainer, I want no `DeleteItem` permission, so that the role reflects that cancellation is an update, not a delete, and the bot can never delete a request row.
15. As the maintainer, I want a Lambda Function URL with auth type `NONE`, so that Slack can reach it directly (Slack's request signature is the authenticator) without the cost and configuration of API Gateway.
16. As the maintainer, I want `terraform output` to surface the Function URL, so that I can copy it straight into the Slack app dashboard.
17. As the maintainer, I want the Lambda configured as `python3.12`, `x86_64`, 256 MB, with a 30-second timeout, so that the lazy listeners' Google Calendar + DynamoDB + manager-DM work completes well within the timeout while staying scale-to-zero.
18. As the maintainer, I want the non-secret configuration (region, table names, `TEAM_CALENDAR_ID`, the `/tmp` path, and the SSM parameter names) as plain Lambda environment variables in Terraform, so that configuration is visible and the secrets are the only thing kept out of state.
19. As the maintainer, I want Terraform state in a shared S3 backend with native locking, so that the deploy is durable and safe for CI or a second operator, and the state (which holds no secrets) is never committed to the repo.
20. As the maintainer, I want the deploy to remain partly HITL — I run the build/apply, set the SSM values, reconfigure the Slack app (disable Socket Mode, set the Request + Interactivity URLs, remove the app-level token), and verify — so that the steps Terraform cannot perform are clearly documented.
21. As the maintainer, I want `smoke_check.py` plus a live `/dayoff` end-to-end run as the acceptance gate, so that I confirm Slack, Calendar, and DynamoDB all work through the deployed Lambda.
22. As the maintainer, I want idle cost confirmed at ~$0, so that the scale-to-zero premise of ADR-0002/ADR-0003 holds in practice.
23. As an employee, I want `/dayoff` and `/dayoff-cancel` to behave exactly as before after the cutover, so that the deployment change is invisible to me.
24. As a manager, I want approval/decline tickets and DMs to work exactly as before after the cutover, so that the deployment change is invisible to me.
25. As a reviewer, I want the SETUP.md production-deploy runbook to list every manual step in order, so that a second operator could execute the cutover without re-deriving it.
26. As the maintainer, I want the design to carry a documented upgrade trigger (Secrets Manager if secret rotation is needed), so that future changes have a recorded rationale rather than re-litigating the trade-off. (Remote state on S3 was the other trigger; it is now adopted.)

## Implementation Decisions

The full decision set is recorded in ADR-0003 (10-row table + alternatives). Key points for implementation:

- **Modules built/modified:**
  - `lambda_handler.py` (modified) — gains a secrets-bootstrap step run lazily on first invocation.
  - `terraform/` (new) — flat root module: `versions.tf` (provider `aws ~> 5.0`, Terraform `>= 1.10`, S3 backend), `variables.tf`, `main.tf`, `outputs.tf`, `terraform.tfvars` (gitignored), and `build.sh`.
  - `seed.create_tables()` (unchanged in code) — re-scoped to "moto-test provisioner only"; Terraform owns prod tables via import.
  - `SETUP.md` and `docs/adr/0003-*.md` — already updated.
- **New interface (the test seam):** a module-level function in `lambda_handler.py` (e.g. `_load_secrets_into_env()`) that reads the three SSM parameter *names* from environment variables, fetches the SecureString values via boto3, sets `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` into `os.environ`, and writes the Google JSON to `/tmp/service-account.json`. `handler()` calls it once, alongside the existing `_handler is None` guard, before constructing the `SlackRequestHandler`.
- **Environment-variable contract (Lambda):** non-secret — `AWS_REGION`, `EMPLOYEES_TABLE`, `REQUESTS_TABLE`, `TEAM_CALENDAR_ID`, `GOOGLE_SERVICE_ACCOUNT_FILE=/tmp/service-account.json`, plus the three SSM parameter names. Secret values come only from SSM at runtime.
- **DynamoDB tables imported, not created:** first `terraform apply` adopts the two live tables (PK + GSI per ADR-0001); their definitions live in Terraform thereafter.
- **IAM:** custom least-privilege policy (actions/resources per user stories 13–14) plus the AWS-managed basic-execution role for logs; `kms:Decrypt` constrained by a `kms:ViaService = ssm.<region>.amazonaws.com` condition.
- **SSM parameters:** Terraform-managed resources with `ignore_changes = [value]`; values set out-of-band post-apply.
- **No code change to** `build_app()`, `CalendarClient`, `db.py`, `requests.py`, or `handlers.py`.

## Testing Decisions

- **What makes a good test here:** assert external behaviour at the seam, not implementation detail. For the bootstrap, that means: given SSM holds the three parameters, the function results in the two Slack env vars being set and the Google JSON file existing with the expected contents — without touching real AWS.
- **Module tested:** the new `_load_secrets_into_env()` seam in `lambda_handler.py`, exercised under `moto`'s `mock_aws` (which covers SSM, mirroring how `tests/conftest.py` already fakes DynamoDB). Seed three parameters with `put_parameter`, call the function, assert `os.environ` is populated and `/tmp/service-account.json` holds the JSON.
- **Existing tests stay green untouched:** `tests/test_lambda_handler.py` constructs via `build_app`/`SlackRequestHandler` directly and never triggers the SSM fetch; the import test only imports. Because the bootstrap runs lazily inside `handler()`, these are unaffected.
- **Prior art:** `tests/conftest.py` (moto `mock_aws` AWS fixture) and `tests/test_lambda_handler.py` (offline Lambda-entrypoint tests, signed-request 200 / bad-signature 401).
- **Terraform is not in the pytest suite.** Infra correctness is verified by `terraform validate` / `terraform plan` and the live `smoke_check.py` + `/dayoff` end-to-end run — the HITL acceptance gate, not an offline unit test.

## Out of Scope

- The actual **HITL live cutover** — running `terraform apply` against the real account, setting the real SSM values, reconfiguring the Slack app dashboard, and the live smoke/end-to-end verification (tracked as the HITL slice).
- **AWS Secrets Manager**, a **CI/CD pipeline**, **arm64**, **container-image packaging**, **API Gateway**, and **automated secret rotation** — all noted as future upgrade triggers in ADR-0003, none built now. (S3 remote state was here too; it is now built.)
- Any change to **bot behaviour**, the **DynamoDB schema**, or the handler/validation/balance logic.
- The **local Socket Mode** dev entrypoint, which is unchanged.

## Further Notes

- **Cross-platform gotcha:** the build must run in WSL (Linux) so wheels match the Amazon Linux x86_64 runtime; building on Windows would produce incompatible binaries for any non-pure-Python dependency.
- **Relationship to existing work:** extends ADR-0002 (Lambda HTTP mode) and the entrypoint from #16; supersedes the "manual AWS console/CLI" framing originally in #17, which has been rewritten to the Terraform approach.
- **Cost:** SSM Parameter Store standard tier + the AWS-managed `aws/ssm` key are $0 within the free tier; the whole stack remains ~$0 idle.