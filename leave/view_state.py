"""Reader for the Slack view-submission envelope — the one place that knows the
shape ``view["state"]["values"][block][action]<leaf>``.

A submission carries each input's value under a per-block, per-action key, with a
leaf that depends on the input type: a plain-text ``value``, a
``selected_option``, a ``selected_date``, a ``selected_user`` (or
``selected_users`` for a multi-picker), or a ``selected_options`` list for a
checkbox. These readers fish the raw leaf out and nothing more — callers still
parse dates/ints and validate.

Pass the ``values`` dict (``view["state"]["values"]``). ``action`` defaults to
``"value"`` — the action_id the block builders use — and is overridden for the
few blocks keyed by a named action id.
"""


def field(values, block, action="value"):
    """The raw input object for one block/action, or ``{}`` when absent."""
    return values.get(block, {}).get(action, {})


def text(values, block, action="value"):
    """A plain-text input's string, or None."""
    return field(values, block, action).get("value")


def option(values, block, action="value"):
    """The chosen value of a select / radio / overflow, or None."""
    chosen = field(values, block, action).get("selected_option")
    return chosen.get("value") if chosen else None


def date_str(values, block, action="value"):
    """A datepicker's raw ISO date string, or None."""
    return field(values, block, action).get("selected_date")


def user(values, block, action="value"):
    """A user-picker's selected user id, or None."""
    return field(values, block, action).get("selected_user")


def users(values, block, action="value"):
    """A multi-user-picker's selected user ids, or ``[]``."""
    return field(values, block, action).get("selected_users") or []


def checkbox_on(values, block, action="value"):
    """Whether a single-option checkbox is ticked."""
    return len(field(values, block, action).get("selected_options") or []) > 0
