# DynamoDB migration 5/5: live AWS provisioning & smoke verification (HITL)

> **Issue:** #15  
> **Labels:** HITL

---

## Parent

#10 — Migrate persistence from Postgres to DynamoDB (pay-per-usage)

## What to build

Provision the real DynamoDB environment and verify the pay-per-usage premise live. This slice is **HITL** — it requires a human to create the AWS account and credentials and run the verification against live infrastructure; it cannot be completed by an AFK agent.

- A human creates the AWS account and an IAM user/role with DynamoDB access, and sets `AWS_REGION` + credentials in the environment.
- Run `seed.create_tables()` against real DynamoDB to provision both tables + the `by_employee` GSI in on-demand mode, and seed the real employees.
- Run `smoke_check.py` against live AWS and confirm a PASS across Slack, Calendar, and DynamoDB.

## Acceptance criteria

- [ ] AWS account + IAM credentials provisioned; `AWS_REGION` and credentials set
- [ ] Both tables + the `by_employee` GSI exist in DynamoDB in on-demand (`PAY_PER_REQUEST`) mode
- [ ] Real employees seeded
- [ ] `smoke_check.py` reports PASS against live AWS (Slack + Calendar + DynamoDB)

## Blocked by

- #14