# Provision the Lambda deploy with Terraform; secrets in SSM SecureString

We provision the production deploy with **Terraform** (a single flat root module under
`terraform/`, S3 remote state) and keep the runtime secrets in **AWS SSM Parameter Store
SecureString**, fetched on cold start. This is the **HITL deploy from #17**, expressed as
infrastructure-as-code instead of console/CLI clicks, and it **resolves the open question
ADR-0002 left** — "supply the Google service-account credentials … bundled in the artifact
or via Secrets Manager / SSM — decided in #17."

Terraform owns the AWS infrastructure: the Lambda, its Function URL, a least-privilege IAM
role, and the two DynamoDB tables. (The plan was to `terraform import` tables pre-provisioned
in #15, but #15 was never run, so the tables didn't exist and Terraform **created** them
directly — one tool owns prod infra either way.) `seed.create_tables()` stays as the moto-test
provisioner, and employee seeding stays a Python data step run **as the human operator** (the
deploy role has no `PutItem` — it manages infra, not data).

Secrets (`SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, and the Google service-account JSON) are
SSM SecureString parameters. `lambda_handler.py` fetches them on cold start, sets the two
Slack values into `os.environ` before `build_app()`, and writes the Google JSON to
`/tmp/service-account.json` so `CalendarClient.from_env()` (which reads a file path) is
**unchanged**. Non-sensitive config — region, table names, `TEAM_CALENDAR_ID`, the
`/tmp` path, the SSM parameter names — stays as plain Lambda env vars in Terraform.

## Decisions at a glance

| # | Decision | Choice |
|---|----------|--------|
| 1 | Infra ownership | Terraform owns + **creates** the 2 DynamoDB tables (#15 never ran, so none pre-existed to import); `seed.create_tables()` → moto tests only |
| 2 | Packaging | Zip via `archive_file`; built in **WSL** (Linux/x86_64 wheels) |
| 3 | Secrets | **SSM Parameter Store SecureString** ($0, out of state); upgrade-to-Secrets-Manager noted |
| 4 | Google creds | Fetched from SSM, written to `/tmp/service-account.json`; only `lambda_handler.py` changes |
| 5 | TF state | **S3 backend** (`your-tfstate-bucket`, key `leave-management/terraform.tfstate`); native lockfile (`use_lockfile`); bucket bootstrapped out-of-band |
| 6 | Code layout | One flat root module in `terraform/`; aws `~> 5.0`, TF `>= 1.10` |
| 7 | Runtime knobs | `python3.12`, `x86_64`, 256 MB, 30 s timeout |
| 8 | IAM | Least-privilege scoped policy (no `DeleteItem`, KMS via-SSM condition, self-invoke) |
| 9 | Build wiring | Decoupled `build.sh` + `terraform apply`, both from WSL |
| 10 | SSM params | Parameters-as-code with `ignore_changes=[value]`; real values set out-of-band |

## Shape

- Flat root module: `versions.tf`, `variables.tf`, `main.tf`, `outputs.tf` (the Function URL),
  `terraform.tfvars` (gitignored). Provider `aws ~> 5.0`, Terraform `>= 1.10` (for native S3
  state locking).
- Resources run in **`ap-southeast-1`** (Singapore). The account's home region `ap-southeast-7`
  (Bangkok) was the first target, but Lambda **Function URLs aren't supported there yet** (it
  returns "FunctionUrlAuthType is not supported in this region"), so compute + data moved to
  `ap-southeast-1`. The Terraform **state bucket stays in `ap-southeast-7`** — a backend's region
  is independent of where resources live.
- The auth-type-`NONE` Function URL needs **two** resource-based grants to principal `*`:
  `lambda:InvokeFunctionUrl` **and** `lambda:InvokeFunction` (an AWS requirement since ~Oct 2025;
  with only the former the URL returns `403 AccessDenied` *before* the function runs).
  `aws_lambda_permission` can't express the tighter `lambda:InvokedViaFunctionUrl` Bool condition,
  so the `InvokeFunction` grant is unconditioned — Slack's in-process signature check is the real
  authenticator, so a direct invoke with an unsigned body is still rejected.
- Remote state in an **S3 backend** with `use_lockfile = true` (native lockfile — no DynamoDB
  lock table) and `encrypt = true`. The state bucket
  (`your-tfstate-bucket`: versioning on, all public access blocked, SSE-S3)
  is created **once out-of-band** and is *not* managed by Terraform. The backend block is
  hardcoded literals (Terraform backends can't take variables).
- Runtime: `python3.12`, `x86_64`, 256 MB, 30 s timeout (above Slack's 3 s so the lazy work
  finishes). The zip is built in **WSL** (`terraform/build.sh`) so wheels are Linux/x86_64;
  `boto3`/`moto`/`pytest` are excluded. `build.sh` then `terraform apply`, both from WSL.
- IAM is least-privilege: `GetItem` on `employees`; `GetItem`/`PutItem`/`UpdateItem`/`Query`
  on `requests` (+ `Query` on the `by_employee` GSI; no `DeleteItem` — cancel is an update);
  `ssm:GetParameter*` on the parameter path; `kms:Decrypt` scoped by `kms:ViaService=ssm`;
  `lambda:InvokeFunction` on its own ARN (lazy listeners self-invoke); `AWSLambdaBasicExecutionRole`
  for logs.
- SSM parameters are declared in Terraform with a placeholder value and
  `lifecycle { ignore_changes = [value] }`; the real values are set out-of-band
  (`aws ssm put-parameter --overwrite`, the Google key via `--value file://service-account.json`),
  so secret values never enter Terraform state.

## Considered alternatives

- **Plaintext Lambda env vars (values via Terraform)** — simplest and no code change, but the
  values, including the Google **private key**, land in Terraform state. Rejected once privacy
  of the key was the priority (it's also $0 either way, so cost didn't decide it).
- **AWS Secrets Manager** — purpose-built rotation, but ~$0.40/secret/month against the ~$0
  goal, with no benefit at 5–20 users. SSM Parameter Store standard tier + the AWS-managed
  `aws/ssm` key is $0.
- **Manual console/CLI deploy** (the original #17 framing) — works, but isn't reproducible or
  reviewable.
- **Local state** — simplest and structurally $0, and was the initial choice while this was a
  solo deploy. Superseded once S3 access was available: remote state is durable and shareable,
  the right base for CI or a second operator, and effectively $0 anyway (a few KB in S3).
- **DynamoDB lock table** for state locking — the long-standing mechanism, but an extra
  bootstrapped resource; the native S3 lockfile (Terraform 1.10+) supersedes it.

## Consequences

- The state bucket must exist before the first `terraform init` (one-time out-of-band CLI
  bootstrap). `.terraform/` and `terraform.tfvars` are gitignored; state lives in S3, not in
  the repo.
- Secret values are **not** recreated by `apply` — after `apply`, set them once via CLI; a
  `terraform destroy`/rebuild needs that step repeated.
- `lambda_handler.py` gains an SSM fetch + `/tmp` write on cold start (adds a little cold-start
  latency and an `ssm`/`kms` dependency).
- Cutover stays partly HITL: the Slack app dashboard (disable Socket Mode, set the Request +
  Interactivity URLs to the Function URL, remove the app-level token) can't be Terraformed, and
  the Request URL doesn't exist until the Lambda + Function URL do.
- Upgrade trigger: move secrets to **Secrets Manager** if rotation is needed. (Remote state on
  S3 is now adopted, so that earlier upgrade trigger is done.)
