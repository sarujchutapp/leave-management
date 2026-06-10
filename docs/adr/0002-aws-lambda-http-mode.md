# Run on AWS Lambda in Slack HTTP mode

We deploy the bot as an AWS Lambda function behind a **Lambda Function URL**, with the
Slack app in **HTTP (Request URL) mode**, instead of a long-running process holding a
Socket Mode WebSocket open. **Socket Mode is kept as the local-development entrypoint.**

This **extends** ADR-0001 from storage to compute. Socket Mode needs an always-on host
(~$3–9/month even while idle), which contradicts the pay-per-usage rationale that drove
the DynamoDB choice. Lambda + a Function URL is scale-to-zero (~$0 idle, within the free
tier at ~5–20 users), so the whole stack — compute and storage — is now pay-per-use.

## Shape

- A shared `build_app(calendar=None, faas=False)` factory builds the Bolt app for both
  run modes. Local dev (`python app.py`) uses Socket Mode; production
  (`lambda_handler.handler`) passes `faas=True`.
- `faas=True` sets `process_before_response=True` and registers the slow handlers
  (approve, decline-submit, cancel — Google Calendar calls + manager DMs) as Bolt **lazy
  listeners**: a quick ack returns inside Slack's 3-second window and the slow work runs
  in a self-invoked second invocation. Handlers that open a modal (need the `trigger_id`
  within 3s) or return validation errors in the ack (`submit_leave`) stay synchronous.
- Auth: HTTP mode verifies request signatures with `SLACK_SIGNING_SECRET` instead of the
  Socket Mode app-level token. `token_verification_enabled=False` skips the startup
  `auth.test` (smoke_check covers token validity; it also avoids a network call per cold
  start).
- Credentials: the Lambda uses an **IAM role** via the standard boto3 chain — no static
  AWS keys — so `db.connect()` is unchanged.

## Considered alternatives

- **Always-on small host** (EC2 `t4g.nano` / Lightsail / Fargate) keeping Socket Mode —
  simplest and needs no code change, but ~$3–9/month idle defeats the cost goal.
- **Lambda + API Gateway** — works, but a Function URL avoids the gateway's extra cost
  and configuration for a single endpoint.

## Consequences

- Lazy listeners self-invoke, so the Lambda's execution role needs `lambda:InvokeFunction`
  on its own function.
- The Lambda timeout must be raised above the 3s default for the lazy work to finish; cold
  starts add latency to the first request.
- `submit_leave`'s no-manager auto-approve still calls the calendar API synchronously and
  may need moving to a lazy listener if cold-start latency trips Slack's 3s there.
- Deployment must exclude test-only dependencies (`moto`, `pytest`) and supply the Google
  service-account credentials to the Lambda (bundled in the artifact or via Secrets
  Manager / SSM — decided in #17).
- Adds a packaging/deploy step and a second Slack app configuration (HTTP mode). The code
  landed in #16; the live deploy + cutover is #17 (HITL).
