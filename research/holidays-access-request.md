# Access request — enable the `leave_holidays` table

**Why:** The holidays table has never been provisioned in prod, so day-counting
silently degrades to "no holidays" (`leave/holidays.py` swallows the missing
table). This over-charges quota for any leave spanning a public holiday **and**
blocks the Leave Optimizer (Pillar 1a), whose whole value is bridging *around*
holidays. Provisioning it is a one-time unblock; no code redesign.

**Account / region:** `<AWS_ACCOUNT_ID>` / `ap-southeast-1`
**Table to create:** `leave_holidays` (partition `year`, sort `holiday_date`)

---

## The one ask — to the AWS account admin

Attach/update the **deploy (Terraform operator) principal's** policy so it can
manage the `leave_holidays` table. The target policy is already committed at
`terraform/operator-policy.json`; the **live** attached policy is missing the
`leave_holidays` ARN (see the note above the deferred table block in
`terraform/main.tf`). The admin needs to make the live policy match the file —
i.e. add this ARN to the existing `DynamoDBManageAndImport` statement:

```
arn:aws:dynamodb:ap-southeast-1:<AWS_ACCOUNT_ID>:table/leave_holidays
```

That statement already grants the right actions (`dynamodb:CreateTable`,
`DescribeTable`, `UpdateTable`, `Describe*`, `Tag*`); only the resource ARN for
the holidays table is missing from what's actually attached.

> Who to ask: whoever administers IAM for account `<AWS_ACCOUNT_ID>` (the program /
> account owner — I don't have `iam:*` on my own principal, by design).

---

## Confirm (probably already fine) — data-load identity

`import_holidays.py` runs as **your own identity** (the script tells you to
`unset AWS_ACCESS_KEY_ID/SECRET/SESSION_TOKEN` first), not the deploy role. It
needs item access on the new table:

```
dynamodb:PutItem, dynamodb:GetItem  on  .../table/leave_holidays
```

Since `add_employees.py` already seeds employees in prod with this same
identity, it likely has broad DynamoDB access already. Just confirm that access
isn't scoped to only `leave_employees` / `leave_requests`.

---

## No ask needed — Lambda runtime read

The bot reads holidays at runtime (`GetItem`/`Query`). Terraform re-adds the
`HolidaysRead` statement to the **Lambda execution role** itself, using the
`iam:PutRolePolicy` grant on `leave-bot-role` the deploy principal already has.
No admin action.

---

## Enablement sequence (once the ask above is granted)

From the note in `terraform/main.tf`:

1. Admin adds the `leave_holidays` ARN to the deploy principal's live policy *(the ask above)*.
2. Restore the `aws_dynamodb_table.holidays` block + the `HolidaysRead` IAM statement in `terraform/main.tf`.
3. `terraform apply` (creates the table + grants the Lambda read).
4. `python import_holidays.py holidays.csv` (loads the dates + mirrors them to the calendar).
