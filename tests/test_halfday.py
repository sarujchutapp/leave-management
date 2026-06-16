from datetime import date

from leave.balance import request_days
from leave.blocks import build_leave_modal
from leave.db import get_employee
from leave.handlers import submit_leave
from leave.requests import (
    approve_request,
    cancellable_requests,
    create_request,
    remaining_balance,
)
from leave.seed import upsert_employee
from leave.validation import validate_request
from tests.fakes import FakeAck, FakeCalendar, FakeSlackClient, make_leave_view


def test_half_day_on_weekday_consumes_half():
    # Wed 2026-06-10, morning half -> 0.5
    assert request_days(date(2026, 6, 10), date(2026, 6, 10), "morning") == 0.5


def test_full_day_request_unchanged():
    assert request_days(date(2026, 6, 10), date(2026, 6, 10), None) == 1


def test_half_day_on_weekend_consumes_nothing():
    # Sat 2026-06-13 is not a working day, so a half of it costs nothing
    assert request_days(date(2026, 6, 13), date(2026, 6, 13), "afternoon") == 0


def test_approved_half_day_deducts_half_from_balance(db):
    upsert_employee(db, "U_A", "Alice", None)  # default vacation allowance 10
    rid = create_request(
        db, "U_A", "vacation", date(2026, 6, 10), date(2026, 6, 10), "x", half="morning"
    )
    approve_request(db, rid)
    emp = get_employee(db, "U_A")
    assert remaining_balance(db, emp, "vacation", date(2026, 6, 1)) == 9.5


def test_half_day_with_date_range_is_rejected(db):
    upsert_employee(db, "U_A", "Alice", None)
    emp = get_employee(db, "U_A")
    errors = validate_request(
        db, emp, "vacation", date(2026, 6, 10), date(2026, 6, 12), date(2026, 6, 1), half="morning"
    )
    assert errors  # a half-day across a multi-day range is invalid


def test_valid_half_day_passes_validation(db):
    upsert_employee(db, "U_A", "Alice", None)
    emp = get_employee(db, "U_A")
    errors = validate_request(
        db, emp, "vacation", date(2026, 6, 10), date(2026, 6, 10), date(2026, 6, 1), half="morning"
    )
    assert errors == {}


def test_submit_half_day_persists_half_and_titles_calendar(db):
    upsert_employee(db, "U_SOLO", "Solo", None)  # no manager -> auto-approve
    calendar = FakeCalendar()
    view = make_leave_view("vacation", "2026-06-10", None, half="morning")

    submit_leave(
        ack=FakeAck(),
        body={"user": {"id": "U_SOLO"}},
        view=view,
        client=FakeSlackClient(),
        db=db,
        calendar=calendar,
        today=date(2026, 6, 1),
    )

    row = cancellable_requests(db, "U_SOLO", date(2026, 6, 1))[0]
    assert row["half"] == "morning"
    assert "morning" in calendar.created[0]["summary"]


def test_modal_has_half_day_selector():
    view = build_leave_modal({"sick": 1, "vacation": 1, "personal": 1})
    block = next(b for b in view["blocks"] if b.get("block_id") == "half_day")
    values = [o["value"] for o in block["element"]["options"]]
    assert values == ["full", "morning", "afternoon"]
