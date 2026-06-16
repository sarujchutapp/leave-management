"""Request validation. Returns a {block_id: message} dict for inline modal
errors; empty dict means valid."""

from leave.balance import request_days
from leave.holidays import holidays_between
from leave.requests import has_overlap, remaining_balance


def validate_request(db, employee, leave_type, start, end, today, half=None):
    errors = {}

    if end < start:
        # Date order is the precondition for the rest; stop here.
        errors["end_date"] = "End date can't be before the start date."
        return errors

    if half and start != end:
        errors["end_date"] = "A half day must be a single date — leave the end date empty."
        return errors

    if start < today:
        errors["start_date"] = "Start date can't be in the past."

    requested = request_days(start, end, half, holidays_between(db, start, end))
    remaining = remaining_balance(db, employee, leave_type, today)
    if requested > remaining:
        errors["leave_type"] = (
            f"Not enough {leave_type} balance: {requested} requested, {remaining} left."
        )

    if has_overlap(db, employee["slack_user_id"], start, end):
        errors["end_date"] = "This overlaps one of your existing requests."

    return errors
