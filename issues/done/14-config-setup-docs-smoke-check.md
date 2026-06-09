# DynamoDB migration 4/5: config, setup docs, smoke-check code

> **Issue:** #14  
> **Labels:** AFK

---

## Parent

#10 — Migrate persistence from Postgres to DynamoDB (pay-per-usage)

## What to build

Replace all remaining Postgres-oriented configuration, setup documentation, and the smoke check with their DynamoDB equivalents, so a new contributor can stand the system up correctly and the repo carries no Postgres references. This is the AFK code/docs portion; the actual live provisioning + verification is the follow-up HITL slice.

- `SETUP.md` §2 (Postgres / Supabase / Neon) is rewritten to: create an AWS account → IAM user with DynamoDB access → set `AWS_REGION` + credentials (+ table names). Reference ADR-0001 for the rationale.
- Environment/config: drop `DATABASE_URL`; add `AWS_REGION`, AWS credentials (standard chain), and table-name config. Update `.env.example` accordingly.
- `smoke_check.py`: replace the Postgres connectivity check with a DynamoDB check (e.g. describe/round-trip against the tables), keeping the Slack and Calendar checks intact.
- Delete `schema.sql`; remove `psycopg` from `requirements.txt`.

## Acceptance criteria

- [ ] `SETUP.md` describes AWS account + IAM + region/credentials instead of Postgres
- [ ] `.env.example` drops `DATABASE_URL` and adds the AWS/table config
- [ ] `smoke_check.py` checks DynamoDB connectivity; Slack and Calendar checks unchanged
- [ ] `schema.sql` deleted and `psycopg` removed from `requirements.txt`
- [ ] No remaining references to Postgres/`DATABASE_URL`/`psycopg` anywhere in the repo

## Blocked by

- #13