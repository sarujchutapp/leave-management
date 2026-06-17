from datetime import date

from leave.calendar_client import CALENDAR_COLOR_IDS, color_id_for
from tests.fakes import FakeAck, FakeCalendar, FakeSlackClient, make_leave_view


def test_color_id_for_is_stable_and_in_range():
    assert color_id_for("U_ALICE") == color_id_for("U_ALICE")  # deterministic
    assert color_id_for("U_ALICE") in CALENDAR_COLOR_IDS


def test_colors_vary_across_people():
    colors = {color_id_for(f"U_{i}") for i in range(11)}
    assert len(colors) > 1  # not everyone the same colour


def test_approved_event_is_coloured_per_person(db):
    from leave.handlers import submit_leave
    from leave.seed import upsert_employee

    upsert_employee(db, "U_SOLO", "Solo", None)  # no manager -> auto-approve
    cal = FakeCalendar()
    submit_leave(
        ack=FakeAck(),
        body={"user": {"id": "U_SOLO"}},
        view=make_leave_view("vacation", "2026-06-10", "2026-06-11"),
        client=FakeSlackClient(),
        db=db,
        calendar=cal,
        today=date(2026, 6, 1),
    )
    assert cal.created[0]["color_id"] == color_id_for("U_SOLO")
