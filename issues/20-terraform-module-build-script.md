# Terraform module + WSL build script for the Lambda deploy

> **Issue:** #20  
> **Labels:** ready-for-agent

---

## Parent

PRD: #18 — Deploy the leave bot to AWS Lambda via Terraform (HTTP-mode cutover)

## What to build

Author the Terraform that provisions the production stack as code, plus the WSL build script that produces the Lambda artifact.

A single flat root module under `terraform/` defines:
- the Lambda function (`python3.12`, `x86_64`, 256 MB, 30 s timeout) from the built zip;
- a **Function URL** (auth type `NONE` — Slack's request signature is the authenticator);
- a **least-privilege IAM role**: `GetItem` on `employees`; `GetItem`/`PutItem`/`UpdateItem`/`Query` on `requests` plus `Query` on the `by_employee` GSI (no `DeleteItem`); `ssm:GetParameter*` on the parameter path; `kms:Decrypt` constrained by `kms:ViaService = ssm.<region>.amazonaws.com`; `lambda:InvokeFunction` on its own ARN (lazy-listener self-invoke); and the AWS-managed basic-execution role for logs;
- the three **SSM SecureString parameters** declared with `lifecycle { ignore_changes = [value] }` and placeholder values (real values set out-of-band in the HITL slice);
- a CloudWatch log group;
- the two existing **DynamoDB tables adopted via `terraform import`** (not recreated), keeping the data from #15.

Non-secret config (`AWS_REGION`, table names, `TEAM_CALENDAR_ID`, `GOOGLE_SERVICE_ACCOUNT_FILE=/tmp/service-account.json`, and the three SSM parameter names) are plain Lambda env vars. `terraform output` exposes the Function URL. State is local and gitignored.

`terraform/build.sh` runs in **WSL**: `pip install` the runtime deps (excluding `boto3`, `moto`, `pytest`), copy `app.py` + `lambda_handler.py` + `leave/` into a build dir that `archive_file` zips and feeds `source_code_hash`. The Google `service-account.json` is **not** bundled (it comes from SSM at runtime).

The live `plan`/`apply` is deferred to the HITL cutover (#17); this slice is verified offline.

## Acceptance criteria

- [ ] `terraform/` flat root module: `versions.tf` (aws `~> 5.0`, Terraform `>= 1.5`), `variables.tf`, `main.tf`, `outputs.tf`; `terraform.tfvars` and local state gitignored
- [ ] Lambda (`python3.12`/`x86_64`/256 MB/30 s), Function URL (auth `NONE`), and CloudWatch log group defined
- [ ] Least-privilege IAM role/policy as specified (no `DeleteItem`; KMS via-SSM condition; self-invoke)
- [ ] Three SSM SecureString parameters declared with `ignore_changes = [value]`; no secret values in config or state
- [ ] The two DynamoDB tables are declared and adopted via `terraform import`, not recreated
- [ ] Non-secret env vars set on the Lambda; `terraform output` exposes the Function URL
- [ ] `build.sh` produces the artifact in WSL excluding `boto3`/`moto`/`pytest`, and does not bundle `service-account.json`
- [ ] `terraform validate` and `terraform fmt -check` pass

## Blocked by

- #19 — the module's env-var contract (SSM parameter names, `GOOGLE_SERVICE_ACCOUNT_FILE=/tmp/...`) must match what the bootstrap reads
