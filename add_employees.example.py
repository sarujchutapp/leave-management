"""Seed / update the real employees in the leave_employees table.

Copy this to `add_employees.py` (gitignored), fill in the EMPLOYEES list with real
member IDs, then run (as yourself, not the deploy role):

    cp add_employees.example.py add_employees.py
    # edit EMPLOYEES
    source .venv/bin/activate
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
    python add_employees.py

- member_id  = Slack profile -> ... (More) -> Copy member ID, from the workspace the bot serves.
- manager_id = that person's approver's member ID, or None for whoever has no approver.
- Re-running is safe: it updates by member_id, so this is also how you edit a name/manager.
  It only writes the fields you pass — an omitted override is left unchanged (not cleared),
  and stored vacation carry_in is preserved.
- Allowances come from the central leave policy (leave/policy.py); pass a 4th item only to
  set a per-person override, e.g. ("U123", "Name", "U_MGR", {"sick": 20, "vacation": 15, "personal": 5}).
"""

import os

os.environ["AWS_REGION"] = "ap-southeast-1"  # the region the bot's tables live in

from leave import db
from leave.seed import upsert_employee

# (member_id, name, manager_id[, allowances]) — manager_id=None for the top of the chain.
EMPLOYEES = [
    ("U_BOSS_ID", "Boss Name", None),
    ("U_ALICE_ID", "Alice Name", "U_BOSS_ID"),
    ("U_BOB_ID", "Bob Name", "U_BOSS_ID"),
]

# Old test/proxy rows to remove (a primary key can't be renamed, so old ids are deleted).
REMOVE = ["U_EXAMPLE_OWNER", "U_EXAMPLE_MEMBER"]


def main():
    handle = db.connect()
    for row in EMPLOYEES:
        upsert_employee(handle, *row)
    for old in REMOVE:
        handle.employees.delete_item(Key={"slack_user_id": old})
    print(f"Upserted {len(EMPLOYEES)} employees; removed {len(REMOVE)} old rows.")


if __name__ == "__main__":
    main()
