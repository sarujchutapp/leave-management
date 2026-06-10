# Fetch Slack and Google secrets from SSM in the Lambda entrypoint

> **Issue:** #19  
> **Labels:** ready-for-agent

---

## Parent

PRD: #18 — Deploy the leave bot to AWS Lambda via Terraform (HTTP-mode cutover)

## What to build

On cold start, the Lambda loads its secrets from AWS SSM Parameter Store (SecureString) instead of relying on plaintext environment variables. Add a bootstrap step in the Lambda entrypoint that reads the three SSM parameter *names* from (non-secret) environment variables, fetches their SecureString values via boto3, sets `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` into the process environment **before** the Bolt app is constructed, and writes the Google service-account JSON to `/tmp/service-account.json` so `CalendarClient.from_env()` (which reads a file path) needs no change.

The bootstrap runs once, lazily, on the first invocation — alongside the existing handler-construction guard. `build_app()`, `CalendarClient`, and the data layer are unchanged. The local Socket Mode entrypoint is unaffected (it never triggers the fetch).

## Acceptance criteria

- [ ] A bootstrap function reads the three SSM parameter names from env vars and fetches their SecureString values via boto3
- [ ] `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` are set into the environment before `build_app()` runs
- [ ] The Google service-account JSON is written to `/tmp/service-account.json` and `GOOGLE_SERVICE_ACCOUNT_FILE` points there
- [ ] The fetch runs once lazily on first invocation; the Socket Mode entrypoint and `build_app()` are unchanged
- [ ] A test under `moto` `mock_aws` seeds the three parameters, runs the bootstrap, and asserts env is populated and the temp file holds the JSON
- [ ] Full suite green offline on moto; no live AWS or Slack required

## Blocked by

- None - can start immediately
