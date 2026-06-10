# Add an AWS Lambda (HTTP-mode) entrypoint with lazy listeners

> **Issue:** #16  
> **Labels:** AFK

---

## Context

Reduce idle hosting cost. Today the bot uses Slack **Socket Mode** (`app.py` →
`SocketModeHandler(...).start()`), which holds a persistent WebSocket open and so
needs an always-on host (~$3–9/mo) — at odds with the pay-per-use DynamoDB choice
(ADR-0001, #10). Switching to **HTTP mode on AWS Lambda + a Function URL** is
scale-to-zero (~$0 idle). This issue is the **AFK code change**; the live deploy +
Slack reconfiguration is the HITL follow-up (#17).

## What to build

- Make the Bolt `App` construction (`build_app()`) importable and **shared** between
  two entrypoints. Keep the existing Socket Mode entrypoint (`python app.py`) for
  **local dev**, unchanged in behavior.
- Add a Lambda entrypoint exporting `handler(event, context)` built on
  `slack_bolt.adapter.aws_lambda.SlackRequestHandler`, so Slack events/interactions
  are processed over HTTP instead of a socket.
- Convert the registered listeners to Bolt **lazy listeners**
  (`App(process_before_response=True)`, `ack=` + `lazy=[...]`) so every interaction
  acks within Slack's **3-second** window and the slow work (Google Calendar API,
  DynamoDB) runs in the lazy function. `leave/handlers.py` already separates ack from
  work, so this is mostly wiring.
- HTTP mode requires request-signature verification: add `SLACK_SIGNING_SECRET` to
  config + `.env.example`; the `SlackRequestHandler` verifies it. `SLACK_APP_TOKEN`
  is only needed by the Socket Mode entrypoint.
- Tests stay offline on moto: assert `build_app()` is importable/constructs, lazy
  listeners are registered, and (thin) that the Lambda `handler` returns 2xx for a
  correctly-signed request and 401 for a bad signature. Don't hit real Slack/AWS.
- Docs: note the two run modes (Socket Mode = local dev, Lambda/HTTP = prod).

## Acceptance criteria

- [ ] `build_app()` is shared; the Socket Mode entrypoint still runs locally with no behavior change
- [ ] A `handler(event, context)` exists using `SlackRequestHandler`, processing Slack events over HTTP
- [ ] Listeners ack within 3s; calendar/DynamoDB work runs in lazy listeners (`process_before_response=True`)
- [ ] `SLACK_SIGNING_SECRET` added to `.env.example` + config and verified on inbound requests
- [ ] Full suite green offline on moto; no change to user-facing behavior
- [ ] No live AWS or Slack reconfiguration required to complete this slice (that is #17)

## Blocked by

- None — code-only, runs/tests offline.
