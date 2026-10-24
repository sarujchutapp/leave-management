# What I learned building this

## The software development life cycle

Every feature went through the same stages, over and over:

1. **Requirements** — someone says what they want in human terms. Ours literally started as a one-line request ("we need a way to book time off in Slack"), then got sharpened into V2 and V3 requirement docs as the ask grew.
2. **Turn vague wants into a spec (a PRD).** Before writing code we'd pin down what the feature actually _is_ — what counts as done, what's out of scope.
3. **Break the spec into tickets.** A PRD became numbered issues in the tracker. There's a folder of 42 finished ones ([`issues/done/`](../issues/done/)). Small, grabbable pieces instead of one giant blob.
4. **Design the tricky bits first** — the ADRs. If a ticket had a real decision in it (how should carry-over work?), that got thought through and written down _before_ coding, not discovered halfway.
5. **Build it on a branch, thin slice first.** Get the simplest working version end-to-end, then add the edges.
6. **Test it** — write the tests that prove it, run the whole suite so nothing old broke.
7. **Review and merge** — the feature branch merges back into `main` as its own commit.
8. **Deploy** — Terraform pushes it to the real cloud.
9. **Maintain** — real usage finds edge cases, those become new tickets, and the loop starts over.

## Even when the test passed doesn't mean it worked

Some code can run perfectly and still be wrong, and telling those apart is basically the whole job.

Best example: my first version of vacation carry-over recomputed everyone's balance from their first day, every year. Ran clean. No errors. Totally wrong — a brand-new hire with no history got handed a full year of carry-over they never earned. Nothing crashed to tell me. I only caught it by _thinking_ about it, not by running it. (That's the whole reason [ADR-0004](adr/0004-carry-over-balance-model.md) exists — we store one small number per person instead.)

Which is why the tests matter so much. The whole suite runs offline — fake AWS, fake Slack, fake Google — so `pytest` finishes in seconds and costs nothing. That's the only reason I could stack half-days on holidays on carry-over without breaking the stuff underneath. Every change ran against every old guarantee instantly.

## Write down the decision

Just like the ADR — a short doc saying "here's what we decided, here's why, here's what we didn't do and why it was worse."

The carry-over one doesn't just say what we built. It lists three other ways to do it and shoots each one down — recompute-live is slow _and_ wrong for new hires, the scheduled job can silently fail to fire, the snapshot breaks the retroactive-holiday thing. That reasoning is the expensive part, and normally it just evaporates the second you forget it. Six months later "why'd we do it this way?" has an actual answer. I never would've thought to write that down before.

Same deal with the glossary ([`CONTEXT.md`](../CONTEXT.md)). It nails down exactly what words mean — a "half day" is exactly 0.5 and can't span multiple dates, a "holiday" doesn't eat your quota, an "admin" is _not_ a "manager."

## New tech

- **Serverless (Lambda).** Costs almost nothing but the catch is "cold start" — the first request after it's been idle is slow enough that Slack can time out. A trade-off between Cheap vs. always-fast.
- **DynamoDB.** Not the SQL tables from class. Had to design around how you read the data first.
- **Terraform.** Describe your cloud setup in a file and one command builds it, instead of clicking around a console.
- **Same code, two ways to run.** Locally it talks to Slack one way, in production another — but the actual logic is identical, only the edges change. Forced me to keep the swappable parts away from the real logic.
- **Least privilege.** The deploy role can build infrastructure but literally can't touch the leave data. It makes sense because if that key leaks, it can't do much. Locking yourself down on purpose _is_ the security.

