"""Request validation. Returns a {block_id: message} dict for inline modal
errors; empty dict means valid."""

from leave.balance import request_days
from leave.holidays import holidays_between
from leave.policy import get_policy
from leave.requests import (
    continuous_absence_length,
    has_overlap,
    pending_days,
    remaining_balance,
)


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
    if requested == 0:
        # All the requested dates are weekends/holidays, which don't consume leave —
        # so the request is meaningless (it would auto-approve for 0 days). Reject it
        # rather than create an empty approved leave + calendar event.
        errors["start_date"] = "That range has no working days — weekends and holidays don't use leave."
        return errors

    # Pending leave reserves quota (ADR-0010): a request can't be filed against days
    # already spoken for by pending or approved leave, so approving any subset can
    # never overshoot. `free` is the approved-only remaining minus what's pending.
    free = remaining_balance(db, employee, leave_type, today) - pending_days(
        db, employee["slack_user_id"], leave_type, today
    )
    if requested > free:
        errors["leave_type"] = (
            f"Not enough {leave_type} balance: {requested} requested, {free} left."
        )

    if has_overlap(db, employee["slack_user_id"], start, end):
        errors["end_date"] = "This overlaps one of your existing requests."

    # Consecutive-absence cap: only full-day vacation requests can create a long run
    # (a half-day is a 'present' day, so it bounds rather than fills).
    if leave_type == "vacation" and not half and "start_date" not in errors:
        cap = get_policy(db)["consecutive_limit"]["vacation"]
        run = continuous_absence_length(db, employee["slack_user_id"], start, end)
        if cap is not None and run > cap:
            errors["start_date"] = (
                f"This would be {run} consecutive days away; the limit is {cap}."
            )

    return errors
