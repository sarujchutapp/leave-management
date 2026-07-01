"""Central leave policy: the single source for base allowances and the carry-over
/ consecutive-limit caps, kept in one place rather than copied onto each employee.

Stored as one reserved item in the `employees` table (PK `__policy__`). Nothing
scans that table — every access is a keyed get — so the reserved row is invisible
to the employee access patterns, and the Lambda's existing GetItem-on-employees
grant already covers reading it. An employee's own `allowances` map, when present,
is a per-person *override*; absent it, balances read this policy.
"""

POLICY_KEY = "__policy__"

# Shipped baseline; an operator can override it without a redeploy by writing the
# reserved item via `set_policy`. Carry-over / consecutive caps are vacation-only.
DEFAULT_POLICY = {
    "allowances": {"sick": 30, "vacation": 10, "personal": 5},
    "max_carry_over": {"vacation": 5},
    "max_total": {"vacation": 15},
    "consecutive_limit": {"vacation": 15},
    # The leave-year reset date (month/day). 1 Jan makes each period a calendar year,
    # so an untouched policy behaves exactly as before.
    "reset_month": 1,
    "reset_day": 1,
}


def _ints(m):
    # A cap may be None ("no limit" — e.g. a disabled consecutive limit); keep it None.
    return {k: (int(v) if v is not None else None) for k, v in m.items()}


def get_policy(db):
    """The central policy. Falls back to DEFAULT_POLICY when no item is set."""
    item = db.employees.get_item(Key={"slack_user_id": POLICY_KEY}).get("Item")
    if item is None:
        return DEFAULT_POLICY
    return {
        "allowances": _ints(item["allowances"]),
        "max_carry_over": _ints(item["max_carry_over"]),
        "max_total": _ints(item["max_total"]),
        "consecutive_limit": _ints(item["consecutive_limit"]),
        # Older items predate the reset date; default them to 1 Jan (calendar year).
        "reset_month": int(item.get("reset_month", DEFAULT_POLICY["reset_month"])),
        "reset_day": int(item.get("reset_day", DEFAULT_POLICY["reset_day"])),
    }


def set_policy(
    db,
    allowances=None,
    max_carry_over=None,
    max_total=None,
    consecutive_limit=None,
    reset_month=None,
    reset_day=None,
):
    """Write the central policy item. Omitted sections keep the shipped defaults.
    The reset date is preserved when not given, so editing the caps or limits never
    silently moves the leave year back to 1 Jan."""
    if reset_month is None or reset_day is None:
        current = get_policy(db)  # stored value, or the 1-Jan default when unseeded
        reset_month = current["reset_month"] if reset_month is None else reset_month
        reset_day = current["reset_day"] if reset_day is None else reset_day
    db.employees.put_item(
        Item={
            "slack_user_id": POLICY_KEY,
            "allowances": allowances or DEFAULT_POLICY["allowances"],
            "max_carry_over": max_carry_over or DEFAULT_POLICY["max_carry_over"],
            "max_total": max_total or DEFAULT_POLICY["max_total"],
            "consecutive_limit": consecutive_limit or DEFAULT_POLICY["consecutive_limit"],
            "reset_month": reset_month,
            "reset_day": reset_day,
        }
    )


def allowance_for(policy, employee, leave_type):
    """Base allowance for one type: the employee's override if set, else central."""
    override = employee.get("allowances") or {}
    if leave_type in override:
        return int(override[leave_type])
    return int(policy["allowances"][leave_type])
