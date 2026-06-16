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
}


def _ints(m):
    return {k: int(v) for k, v in m.items()}


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
    }


def set_policy(db, allowances=None, max_carry_over=None, max_total=None, consecutive_limit=None):
    """Write the central policy item. Omitted sections keep the shipped defaults."""
    db.employees.put_item(
        Item={
            "slack_user_id": POLICY_KEY,
            "allowances": allowances or DEFAULT_POLICY["allowances"],
            "max_carry_over": max_carry_over or DEFAULT_POLICY["max_carry_over"],
            "max_total": max_total or DEFAULT_POLICY["max_total"],
            "consecutive_limit": consecutive_limit or DEFAULT_POLICY["consecutive_limit"],
        }
    )


def allowance_for(policy, employee, leave_type):
    """Base allowance for one type: the employee's override if set, else central."""
    override = employee.get("allowances") or {}
    if leave_type in override:
        return int(override[leave_type])
    return int(policy["allowances"][leave_type])
