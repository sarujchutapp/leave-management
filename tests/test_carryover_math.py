"""Pure carry-over arithmetic — no DB, no employee rows, no re-fetch dance.

The balance-model rules from ADR-0004, exercised directly as plain math (contrast
test_carryover.py, which drives the same rules through the store)."""

from leave.carryover import next_carry, roll_forward

# Baseline company policy in these tests: base 10, max_carry 5, max_total 15.


def test_leftover_carries_capped_at_max_carry():
    # Used 4 of 10 -> leftover 6, but only 5 may roll out.
    assert next_carry(10, 5, 15, 0, 4) == 5


def test_using_everything_carries_nothing():
    assert next_carry(10, 5, 15, 0, 10) == 0


def test_carry_never_goes_negative_when_overused():
    # An admin cap cut can drive usage past availability; carry floors at 0.
    assert next_carry(10, 5, 15, 0, 12) == 0


def test_max_total_caps_availability_before_carry_out():
    # available = min(10 + carry 5, 12) = 12; used 0 -> min(12, max_carry 5) = 5.
    assert next_carry(10, 5, 12, 5, 0) == 5


def test_roll_forward_feeds_each_period_into_the_next():
    # Period 1 uses 4 -> carry 5. Period 2 uses 0 -> available min(15,15)=15,
    # leftover 15 capped at max_carry 5.
    assert roll_forward(10, 5, 15, 0, [4, 0]) == [5, 5]


def test_roll_forward_empty_is_no_periods():
    assert roll_forward(10, 5, 15, 3, []) == []
