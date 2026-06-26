# Keep the Lambda warm with a scheduled ping

A scheduled EventBridge rule pings the Lambda every 5 minutes (`rate(5 minutes)`,
around the clock) with a `{"warmup": true}` event. The handler treats that event as a
prime-and-return: it loads the SSM secrets and builds the Bolt app (the cold-start
work), then returns *before* the Slack request path. We do **not** move to an always-on
host or provisioned concurrency.

This **refines** ADR-0002 (Lambda + HTTP mode); it does not reverse it.

## Why

`/dayoff` opens a modal, so it must run synchronously (the `trigger_id` is valid for
only ~3s, and lazy listeners self-invoke too late to use it). Under `faas=True` the app
runs with `process_before_response=True`, which means the HTTP ack is not flushed when
`ack()` is called — only when the handler returns, **after** the `views_open`
round-trip. On a cold start the chain `import + SSM + build_app + get_employee +
remaining_balances + views_open` occasionally exceeds 3s. The modal still opens (the
trigger outlives the late ack by a hair), but Slack shows `operation_timeout`. Warm, the
same chain is well under 1s. The message is Slack-generated — there is no app-side way to
suppress or restyle it; the only cure is to ack in time, i.e. not be cold.

## Why 24/7 doesn't betray the pay-per-usage model

The model lives where cost actually grows with usage — **DynamoDB on-demand,
pay-per-query (ADR-0001)**. The warm-up ping **never queries DynamoDB**: it short-circuits
before any handler runs, so it issues no reads/writes. The pay-per-query layer is
untouched — it still charges exactly per real query.

ADR-0002 extended the idea to compute, but its actual concern was *paying ~$3–9/month for
idle compute* — not idleness as a virtue. A keep-warm ping's idle cost is **$0**: ~8,600
tiny invocations/month sit far inside Lambda's perpetual free tier (1M requests +
400k GB-s), and the ping does no DB I/O. So ADR-0002's "don't pay for idle" rationale is
satisfied by a different route than literal scale-to-zero, at any hour. Pinging only
during business hours would have spared a purity (the compute layer literally idling
off-hours) that costs nothing and isn't the point — so we ping around the clock and kill
the message at every hour instead.

## Shape

- `lambda_handler.handler`: after priming secrets + app (the existing first-invocation
  bootstrap), `if event.get("warmup"): return {"ok": True}` — short-circuits before the
  Slack request path, which expects a signed HTTP event. No DynamoDB access on this path.
- Terraform: an `aws_cloudwatch_event_rule` (`rate(5 minutes)`), an
  `aws_cloudwatch_event_target` whose `input` is `{"warmup": true}`, and an
  `aws_lambda_permission` letting EventBridge invoke the function.

## Considered alternatives

- **Do nothing (pure scale-to-zero).** Also $0 and architecturally cleanest, but eats the
  occasional cold-start `operation_timeout` — the price of a container that truly dies
  when idle.
- **Business-hours-only ping.** Keeps the compute layer literally idle nights/weekends,
  but that purity costs nothing and buys nothing the user sees, while leaving an off-hours
  cold-start message. Rejected for plain 24/7.
- **Hide / restyle the message.** Not possible — it is Slack-side, triggered solely by
  missing the 3s ack.
- **Reorder `ack()` earlier / lazy-listen the modal.** No effect under
  `process_before_response` (the ack flushes after the handler), and lazy listeners can't
  open modals reliably (the `trigger_id` expires across the self-invocation).
- **Always-on host keeping Socket Mode** (weighed in ADR-0002). Removes the message and
  needs ~no code change, but ~$3–9/month idle — it pays for idle, which is the thing
  ADR-0002 set out to avoid.
- **Provisioned concurrency.** Guaranteed warm, but ongoing $ for idle capacity.
- **SnapStart (Python).** Snapshots the init phase and covers concurrent cold starts too,
  but needs a published version + alias + a Function-URL repoint, and our secrets are
  fetched at runtime (post-restore), so the win is partial without an `afterRestore` hook.
  More moving parts than the problem warrants today.

## Consequences

- The Lambda no longer *literally* scales to zero (it is invoked every 5 min), but that
  was only ever a means to "no idle cost," which still holds ($0), and the cost-bearing
  layer (DynamoDB) stays pay-per-query and untouched.
- A *simultaneous* second `/dayoff` in the same cold instant can still hit a cold
  container (keep-warm holds one warm). Rare at this team size; SnapStart or provisioned
  concurrency is the lever if that ever matters.
- The execution role already allows the function to be invoked; the new permission only
  adds the EventBridge principal for this rule.
