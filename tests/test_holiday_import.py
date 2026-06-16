from datetime import date

from leave.holidays import apply_holidays, get_holiday, holidays_for_year, parse_holiday_rows
from tests.fakes import FakeCalendar


def test_apply_holidays_creates_event_and_stores_id(db):
    cal = FakeCalendar()
    apply_holidays(db, cal, [(date(2026, 4, 13), "Songkran")])

    assert holidays_for_year(db, 2026) == {date(2026, 4, 13)}
    row = get_holiday(db, date(2026, 4, 13))
    assert row["label"] == "Songkran"
    assert row["calendar_event_id"] == cal.created[0]["id"]
    assert "Songkran" in cal.created[0]["summary"]
    assert len(cal.created) == 1


def test_reimport_updates_event_without_duplicating(db):
    cal = FakeCalendar()
    apply_holidays(db, cal, [(date(2026, 4, 13), "Songkran")])
    apply_holidays(db, cal, [(date(2026, 4, 13), "Songkran Festival")])  # edited label

    assert len(cal.created) == 1  # no duplicate event created
    assert cal.updated[-1]["summary"] == "Holiday: Songkran Festival"
    assert get_holiday(db, date(2026, 4, 13))["label"] == "Songkran Festival"


def test_apply_is_add_update_only(db):
    cal = FakeCalendar()
    apply_holidays(db, cal, [(date(2026, 4, 13), "Songkran")])
    # A later import without Songkran must not remove it.
    apply_holidays(db, cal, [(date(2026, 5, 1), "Labour Day")])
    assert holidays_for_year(db, 2026) == {date(2026, 4, 13), date(2026, 5, 1)}


def test_parse_holiday_rows_skips_header_and_blanks():
    raw = [["date", "label"], ["2026-04-13", "Songkran"], [], ["2026-12-31", " NYE "]]
    assert parse_holiday_rows(raw) == [
        (date(2026, 4, 13), "Songkran"),
        (date(2026, 12, 31), "NYE"),
    ]
