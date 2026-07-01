from datetime import date

import pytest

from leave.holidays import (
    HolidayImportError,
    apply_holidays,
    get_holiday,
    holidays_for_year,
    parse_holiday_rows,
    parse_holiday_text,
)
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


def test_parse_holiday_text_comma():
    raw = "2026-04-13,Songkran\n2026-05-01,Labour Day"
    assert parse_holiday_text(raw) == [
        (date(2026, 4, 13), "Songkran"),
        (date(2026, 5, 1), "Labour Day"),
    ]


def test_parse_holiday_text_tab_is_identical():
    """An Excel/Sheets copy yields tab-delimited rows — parses the same as commas."""
    raw = "2026-04-13\tSongkran\n2026-05-01\tLabour Day"
    assert parse_holiday_text(raw) == [
        (date(2026, 4, 13), "Songkran"),
        (date(2026, 5, 1), "Labour Day"),
    ]


def test_parse_holiday_text_preserves_comma_in_label():
    """Splitting on the first delimiter only keeps a label's own commas intact."""
    assert parse_holiday_text("2026-12-31,New Year's Eve, observed") == [
        (date(2026, 12, 31), "New Year's Eve, observed"),
    ]


def test_parse_holiday_text_skips_header_and_blanks():
    raw = "date,label\n2026-04-13,Songkran\n\n2026-12-31, NYE "
    assert parse_holiday_text(raw) == [
        (date(2026, 4, 13), "Songkran"),
        (date(2026, 12, 31), "NYE"),
    ]


def test_parse_holiday_text_rejects_unparseable_date():
    with pytest.raises(HolidayImportError) as exc:
        parse_holiday_text("2026-04-13,Songkran\nnotadate,Labour Day")
    assert any("2" in msg for msg in exc.value.errors)  # names line 2
    assert len(exc.value.errors) == 1


def test_parse_holiday_text_rejects_missing_label():
    with pytest.raises(HolidayImportError) as exc:
        parse_holiday_text("2026-04-13,Songkran\n2026-05-01")  # no label
    assert any("2" in msg for msg in exc.value.errors)
    assert len(exc.value.errors) == 1


def test_parse_holiday_text_rejects_empty_paste():
    for raw in ("", "   \n\t  "):
        with pytest.raises(HolidayImportError) as exc:
            parse_holiday_text(raw)
        assert exc.value.errors  # a clear, non-empty message


def test_parse_holiday_text_names_every_offending_line():
    """All-or-nothing: one bad date and one missing label are both reported."""
    with pytest.raises(HolidayImportError) as exc:
        parse_holiday_text("nope,Foo\n2026-05-01,Labour Day\n2026-06-01")
    assert len(exc.value.errors) == 2
    assert any("1" in m for m in exc.value.errors)
    assert any("3" in m for m in exc.value.errors)
