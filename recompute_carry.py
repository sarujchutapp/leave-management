"""Rebuild a stored vacation carry_in after an already-closed year was edited
(e.g. a holiday added retroactively to a prior year). Run as yourself, not the
deploy role:

    source .venv/bin/activate
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
    python recompute_carry.py <slack_user_id> <year>

Drops carry_in from <year> forward and recomputes it from the stored chain.
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("AWS_REGION", "ap-southeast-1")

from leave import db
from leave.db import get_employee
from leave.requests import recompute_carry_in


def main():
    slack_user_id, year = sys.argv[1], int(sys.argv[2])
    handle = db.connect()
    employee = get_employee(handle, slack_user_id)
    if employee is None:
        sys.exit(f"No employee {slack_user_id}")
    value = recompute_carry_in(handle, employee, year)
    print(f"Recomputed carry_in[{year}] for {slack_user_id}: {value}")


if __name__ == "__main__":
    main()
