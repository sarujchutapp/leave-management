"""Vacation carry-over arithmetic — pure math, no DB and no Slack.

Carry-over (CONTEXT.md) is unused vacation from one leave period made available
in the next, bounded by two company-wide caps: `max_carry_over` on how many days
may roll OUT of a period, and `max_total` on how much vacation is available
WITHIN a period. This module owns the roll-forward — given the caps, the base
allowance, the carry into some period, and the vacation used in each following
period, it produces the carry into each of those periods in turn. Sick and
personal never carry; only vacation reaches here.
"""


def next_carry(base, max_carry, max_total, carry_in, used):
    """Vacation days rolling OUT of one period into the next: the period's
    availability (`base` plus the carry into it, capped at `max_total`) minus the
    days `used`, floored at zero, then capped at `max_carry`."""
    available = min(base + carry_in, max_total)
    return min(max(available - used, 0), max_carry)


def roll_forward(base, max_carry, max_total, start_carry, used_per_period):
    """Roll `start_carry` forward through consecutive periods. `used_per_period`
    is the vacation used in each period, in order; returns the carry into each of
    those following periods (one value per entry, same order), each period's carry
    feeding the next period's availability."""
    carry, out = start_carry, []
    for used in used_per_period:
        carry = next_carry(base, max_carry, max_total, carry, used)
        out.append(carry)
    return out
