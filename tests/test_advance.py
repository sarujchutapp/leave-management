"""Handler-seam tests for /advance (the longest-break tracer). The optimizer
math is covered directly in test_optimizer.py; here we test the gather + reply."""

from datetime import date

from leave.handlers import ADVANCE_NOTHING, CONTACT_ADMIN, _suggest_longest_break, open_advance
from leave.seed import upsert_employee
from leave.validation import validate_request
from leave.db import get_employee
from tests.fakes import FakeAck

TODAY = date(2026, 6, 8)  # a Monday


def test_unregistered_user_gets_contact_admin(db):
    ack = FakeAck()
    open_advance(ack=ack, body={"user_id": "U_NOPE"}, db=db, today=TODAY)
    assert ack.response == CONTACT_ADMIN


def test_caller_with_balance_gets_a_break(db):
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    ack = FakeAck()
    open_advance(ack=ack, body={"user_id": "U_A"}, db=db, today=TODAY)
    assert "days off" in ack.response
    assert "Book vacation" in ack.response


def test_top_of_chain_caller_gets_a_result(db):
    # No manager (top of chain) — /advance still suggests a break.
    upsert_employee(db, "U_SOLO", "Solo", None, allowances={"vacation": 5})
    ack = FakeAck()
    open_advance(ack=ack, body={"user_id": "U_SOLO"}, db=db, today=TODAY)
    assert ack.response != ADVANCE_NOTHING
    assert "Book vacation" in ack.response


def test_no_balance_gets_nothing_to_suggest(db):
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 0})
    ack = FakeAck()
    open_advance(ack=ack, body={"user_id": "U_A"}, db=db, today=TODAY)
    assert ack.response == ADVANCE_NOTHING


def test_suggested_break_passes_validation(db):
    # The whole point of sourcing inputs from the request flow: the break is
    # always bookable. Take the suggestion and run it through validate_request.
    upsert_employee(db, "U_A", "Alice", None, allowances={"vacation": 5})
    emp = get_employee(db, "U_A")
    brk = _suggest_longest_break(db, emp, TODAY)
    assert brk is not None
    errors = validate_request(db, emp, "vacation", brk.book_start, brk.book_end, TODAY)
    assert errors == {}
