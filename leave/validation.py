"""Request validation. Returns a {block_id: message} dict for inline modal
errors; empty dict means valid."""

from leave.balance import count_weekdays
from leave.requests import has_overlap, remaining_balance


def validate_request(conn, employee, leave_type, start, end, today):
    errors = {}

    if end < start:
        # Date order is the precondition for the rest; stop here.
        errors["end_date"] = "End date can't be before the start date."
        return errors

    if start < today:
        errors["start_date"] = "Start date can't be in the past."

    requested = count_weekdays(start, end)
    remaining = remaining_balance(conn, employee, leave_type, today)
    if requested > remaining:
        errors["leave_type"] = (
            f"Not enough {leave_type} balance: {requested} requested, {remaining} left."
        )

    if has_overlap(conn, employee["slack_user_id"], start, end):
        errors["end_date"] = "This overlaps one of your existing requests."

    return errors
