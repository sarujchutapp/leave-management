"""Per-employee approval mode — the one home for the auto-vs-ticket rule.

A leaf module (no DB, no Slack) so both the handler routing and the Manage-employees
modal can share it without a circular import.
"""


def resolve_approval_mode(employee):
    """The request's approval mode for this employee: `auto` (skip the ticket) or
    `approval-needed` (route a ticket). Reads the stored `approval` when present;
    when the field is absent, derives it to preserve today's behavior — `auto` for a
    self-managed or no-manager employee, `approval-needed` otherwise (the old
    `_self_approves` rule). No backfill of existing records."""
    stored = employee.get("approval")
    if stored in ("auto", "approval-needed"):
        return stored
    if employee["manager_id"] is None or employee["manager_id"] == employee["slack_user_id"]:
        return "auto"
    return "approval-needed"
