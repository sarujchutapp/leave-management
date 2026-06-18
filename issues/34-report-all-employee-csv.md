# V3 #5: Report — all-employee usage/quota CSV

- **URL:** #34
- **Labels:** ready-for-agent

## Parent

V3: Admin control plane in Slack (`/control`) — #29

## What to build

The **Report** action: an admin gets a downloadable CSV of every employee's leave usage and remaining quota, delivered privately.

- The "Report" button generates a CSV via a pure `db → CSV text` function with columns: employee, leave type, used, remaining, carry-in — using `remaining_balances` + `approved_weekdays_by_type_this_year` over all employees (a `Scan` on `employees`).
- The handler uploads the CSV to the **admin's DM** via `files_upload_v2` (so it's a downloadable file with a link, and everyone's data isn't posted to a shared channel).
- Generation + upload run **post-ack** (lazy listener on Lambda, inline in Socket Mode).

## Acceptance criteria

- [ ] Report produces a CSV with one row per employee × leave type, columns: employee, leave type, used, remaining, carry-in.
- [ ] The CSV figures match the derived balances (`remaining_balances` / used-this-year).
- [ ] The file is uploaded to the requesting admin's DM, not a shared channel.
- [ ] Generation + upload run post-ack so the interaction acks within 3s.
- [ ] Non-admin submit is rejected.
- [ ] Terraform: Lambda execution role gains `dynamodb:Scan` on the `employees` table.
- [ ] The `files:write` Slack scope requirement is documented (SETUP / .env notes) as a deploy-time step.
- [ ] Offline tests cover the CSV-rendering function directly, and a `files_upload_v2` recorder added to `FakeSlackClient` verifies the upload target.

## Blocked by

- V3 #1: /control skeleton (#30)
