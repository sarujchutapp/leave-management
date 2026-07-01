from datetime import date

from leave.blocks import build_cancel_modal
from leave.db import get_employee
from leave.handlers import (
    CANNOT_CANCEL,
    NOTHING_TO_CANCEL,
    open_cancel_modal,
    submit_cancel,
)
from leave.requests import (
    approve_request,
    can_cancel,
    cancel_request,
    cancellable_requests,
    create_request,
    decline_request,
    early_return,
    early_return_reclaim_days,
    get_request,
    is_early_returnable,
    is_in_progress,
    remaining_balance,
    set_calendar_event_id,
    set_ticket_ref,
)
from leave.seed import upsert_employee
from tests.fakes import FakeAck, FakeCalendar, FakeSlackClient, make_cancel_view

TODAY = date(2026, 6, 8)  # Monday
FUTURE_START = date(2026, 6, 10)
FUTURE_END = date(2026, 6, 11)
# In-progress: started last Thu, runs to this Fri. Tail after today (Tue–Fri) = 4 weekdays.
INPROGRESS_START = date(2026, 6, 4)
INPROGRESS_END = date(2026, 6, 12)


def _people(db):
    upsert_employee(db, "U_BOSS", "Boss", None)
    upsert_employee(db, "U_ALICE", "Alice", "U_BOSS")
    upsert_employee(db, "U_BOB", "Bob", "U_BOSS")


def _approved_future(db):
    rid = create_request(db, "U_ALICE", "vacation", FUTURE_START, FUTURE_END, None)
    approve_request(db, rid)
    set_calendar_event_id(db, rid, "evtX")
    return rid


def _approved_in_progress(db):
    rid = create_request(db, "U_ALICE", "vacation", INPROGRESS_START, INPROGRESS_END, None)
    approve_request(db, rid)
    set_calendar_event_id(db, rid, "evtIP")
    return rid


def _status(db, rid):
    return get_request(db, rid)["status"]


def _cancel(db, rid, user, calendar=None, client=None, today=TODAY):
    submit_cancel(
        ack=FakeAck(),
        body={"user": {"id": user}},
        view=make_cancel_view(rid),
        client=client or FakeSlackClient(),
        db=db,
        calendar=calendar or FakeCalendar(),
        today=today,
    )


# --- early-return: requests.py seam ---------------------------------------

def test_cancellable_includes_in_progress(db):
    _people(db)
    ip = _approved_in_progress(db)
    fut = _approved_future(db)
    ids = {r["request_id"] for r in cancellable_requests(db, "U_ALICE", TODAY)}
    assert ip in ids and fut in ids


def test_is_in_progress_classification(db):
    _people(db)
    ip = get_request(db, _approved_in_progress(db))
    fut = get_request(db, _approved_future(db))
    assert is_in_progress(ip, TODAY) is True
    assert is_in_progress(fut, TODAY) is False  # not yet started


def test_early_return_reclaim_counts_only_days_after_today(db):
    _people(db)
    ip = get_request(db, _approved_in_progress(db))
    # Runs Jun 4–12; today Jun 8. Tail Jun 9–12 = Tue,Wed,Thu,Fri = 4 weekdays.
    assert early_return_reclaim_days(db, ip, TODAY) == 4


def test_early_return_shortens_end_and_refunds_tail(db):
    _people(db)
    rid = _approved_in_progress(db)
    alice = get_employee(db, "U_ALICE")
    before = remaining_balance(db, alice, "vacation", TODAY)  # Jun 4–12 = 7 weekdays used

    early_return(db, rid, TODAY)

    r = get_request(db, rid)
    assert r["end_date"] == TODAY
    assert r["status"] == "approved"  # still approved; days through today stay taken
    assert remaining_balance(db, alice, "vacation", TODAY) == before + 4  # tail refunded


# --- early-return guards & atomicity: requests.py seam (#54) ---------------

def test_early_return_conditional_applies_once(db):
    _people(db)
    rid = _approved_in_progress(db)
    assert early_return(db, rid, TODAY) is True  # first shortens
    assert early_return(db, rid, TODAY) is False  # already at today — a double-submit no-ops
    assert get_request(db, rid)["end_date"] == TODAY


def test_early_return_skipped_when_no_longer_approved(db):
    _people(db)
    rid = _approved_in_progress(db)
    cancel_request(db, rid)  # a racing cancel wins first
    assert early_return(db, rid, TODAY) is False
    assert get_request(db, rid)["end_date"] == INPROGRESS_END  # end unchanged


def test_leave_ending_today_not_early_returnable(db):
    _people(db)
    rid = create_request(db, "U_ALICE", "vacation", INPROGRESS_START, TODAY, None)
    approve_request(db, rid)
    r = get_request(db, rid)
    assert is_early_returnable(db, r, TODAY) is False  # nothing after today to return
    assert rid not in {x["request_id"] for x in cancellable_requests(db, "U_ALICE", TODAY)}


def test_remaining_all_weekend_not_early_returnable(db):
    _people(db)
    friday = date(2026, 6, 12)  # tail Sat–Sun has no working days
    rid = create_request(db, "U_ALICE", "vacation", date(2026, 6, 10), date(2026, 6, 14), None)
    approve_request(db, rid)
    r = get_request(db, rid)
    assert early_return_reclaim_days(db, r, friday) == 0
    assert is_early_returnable(db, r, friday) is False
    assert rid not in {x["request_id"] for x in cancellable_requests(db, "U_ALICE", friday)}


def test_half_day_never_early_returnable(db):
    _people(db)
    rid = create_request(db, "U_ALICE", "vacation", TODAY, TODAY, None, half="morning")
    approve_request(db, rid)
    r = get_request(db, rid)
    assert is_early_returnable(db, r, TODAY) is False
    assert rid not in {x["request_id"] for x in cancellable_requests(db, "U_ALICE", TODAY)}


# --- build_cancel_modal seam ----------------------------------------------

def test_cancel_modal_marks_in_progress(db):
    _people(db)
    _approved_in_progress(db)
    _approved_future(db)
    rows = cancellable_requests(db, "U_ALICE", TODAY)
    view = build_cancel_modal(rows, TODAY)
    texts = [o["text"]["text"] for o in view["blocks"][0]["element"]["options"]]
    assert any("(in progress)" in t for t in texts)  # the underway leave is marked
    assert any("(approved)" in t for t in texts)  # the future one keeps its status


# --- pure rule -------------------------------------------------------------

def test_can_cancel_rules():
    assert can_cancel({"status": "pending", "start_date": FUTURE_START, "end_date": FUTURE_END}, TODAY) is True
    assert can_cancel({"status": "approved", "start_date": FUTURE_START, "end_date": FUTURE_END}, TODAY) is True
    # in progress (start ≤ today ≤ end) is now cancellable — it becomes an early return
    assert can_cancel({"status": "approved", "start_date": INPROGRESS_START, "end_date": INPROGRESS_END}, TODAY) is True
    # fully past — nothing to cancel
    assert can_cancel({"status": "approved", "start_date": date(2026, 6, 1), "end_date": date(2026, 6, 2)}, TODAY) is False
    assert can_cancel({"status": "declined", "start_date": FUTURE_START, "end_date": FUTURE_END}, TODAY) is False


# --- submit_cancel ---------------------------------------------------------

def test_cancel_pending(db):
    _people(db)
    rid = create_request(db, "U_ALICE", "vacation", FUTURE_START, FUTURE_END, None)
    calendar = FakeCalendar()

    _cancel(db, rid, "U_ALICE", calendar=calendar)

    assert _status(db, rid) == "cancelled"
    assert calendar.deleted == []  # nothing on the calendar for a pending request


def test_cancel_pending_withdraws_manager_ticket(db):
    _people(db)
    rid = create_request(db, "U_ALICE", "vacation", FUTURE_START, FUTURE_END, None)
    set_ticket_ref(db, rid, "D1", "9.9")
    client = FakeSlackClient()

    _cancel(db, rid, "U_ALICE", client=client)

    assert _status(db, rid) == "cancelled"
    assert len(client.chat_update_calls) == 1
    assert client.chat_update_calls[0]["channel"] == "D1"
    assert client.chat_update_calls[0]["ts"] == "9.9"


def test_cancel_approved_before_start_deletes_event_and_notifies_manager(db):
    _people(db)
    rid = _approved_future(db)
    client, calendar = FakeSlackClient(), FakeCalendar()

    _cancel(db, rid, "U_ALICE", calendar=calendar, client=client)

    assert _status(db, rid) == "cancelled"
    assert calendar.deleted == ["evtX"]
    assert "U_BOSS" in [c["channel"] for c in client.chat_postMessage_calls]  # manager FYI


def test_cancel_refunds_balance(db):
    _people(db)
    rid = _approved_future(db)
    alice = get_employee(db, "U_ALICE")
    assert remaining_balance(db, alice, "vacation", TODAY) == 8  # Wed-Thu used

    _cancel(db, rid, "U_ALICE")
    assert remaining_balance(db, alice, "vacation", TODAY) == 10


def test_cannot_cancel_approved_after_start(db):
    _people(db)
    rid = create_request(db, "U_ALICE", "vacation", date(2026, 6, 1), date(2026, 6, 2), None)
    approve_request(db, rid)
    client = FakeSlackClient()

    _cancel(db, rid, "U_ALICE", client=client)

    assert _status(db, rid) == "approved"
    assert client.chat_postMessage_calls[0]["text"] == CANNOT_CANCEL


def test_cancel_on_vanished_request(db):
    # The row is deleted (e.g. /control Clear) between opening the cancel modal and
    # submitting it. Submit must not crash — the user is told it's gone.
    _people(db)
    rid = create_request(db, "U_ALICE", "vacation", FUTURE_START, FUTURE_END, None)
    db.requests.delete_item(Key={"request_id": rid})
    client = FakeSlackClient()

    _cancel(db, rid, "U_ALICE", client=client)

    assert client.chat_postMessage_calls[0]["text"] == CANNOT_CANCEL


def test_other_user_cannot_cancel(db):
    _people(db)
    rid = create_request(db, "U_ALICE", "vacation", FUTURE_START, FUTURE_END, None)

    _cancel(db, rid, "U_BOB")

    assert _status(db, rid) == "pending"


# --- early return via submit_cancel ---------------------------------------

def test_early_return_shortens_redates_calendar_and_dms(db):
    _people(db)
    rid = _approved_in_progress(db)
    alice = get_employee(db, "U_ALICE")
    before = remaining_balance(db, alice, "vacation", TODAY)
    client, calendar = FakeSlackClient(), FakeCalendar()

    _cancel(db, rid, "U_ALICE", calendar=calendar, client=client)

    r = get_request(db, rid)
    assert r["status"] == "approved"  # not cancelled — shortened
    assert r["end_date"] == TODAY
    assert remaining_balance(db, alice, "vacation", TODAY) == before + 4  # tail returned
    # calendar re-dated: old event deleted, a new [start, today] event stored
    assert calendar.deleted == ["evtIP"]
    assert len(calendar.created) == 1
    assert calendar.created[0]["start"] == INPROGRESS_START
    assert calendar.created[0]["end"] == TODAY
    assert r["calendar_event_id"] == calendar.created[0]["id"]
    # employee result DM explains it ended early, kept through today, days returned
    dm = next(c for c in client.chat_postMessage_calls if c["channel"] == "U_ALICE")["text"]
    assert "early" in dm.lower()
    assert TODAY.isoformat() in dm
    assert "4" in dm


def test_early_return_fyis_distinct_manager(db):
    _people(db)
    rid = _approved_in_progress(db)
    client = FakeSlackClient()

    _cancel(db, rid, "U_ALICE", client=client)

    fyi = [c for c in client.chat_postMessage_calls if c["channel"] == "U_BOSS"]
    assert len(fyi) == 1
    assert "early" in fyi[0]["text"].lower()


def test_early_return_second_submit_fires_no_duplicate_side_effects(db):
    _people(db)
    rid = _approved_in_progress(db)
    _cancel(db, rid, "U_ALICE")  # first submit applies the early return

    client2, cal2 = FakeSlackClient(), FakeCalendar()
    _cancel(db, rid, "U_ALICE", calendar=cal2, client=client2)  # stale/racing re-submit

    assert cal2.deleted == [] and cal2.created == []  # no second calendar re-date
    assert get_request(db, rid)["end_date"] == TODAY  # unchanged
    assert client2.chat_postMessage_calls[0]["text"] == CANNOT_CANCEL  # reports it didn't apply


def test_early_return_no_fyi_for_self_approver(db):
    upsert_employee(db, "U_SOLO", "Solo", None)  # top of chain — self-approves
    rid = create_request(db, "U_SOLO", "vacation", INPROGRESS_START, INPROGRESS_END, None)
    approve_request(db, rid)
    set_calendar_event_id(db, rid, "evtSolo")
    client = FakeSlackClient()

    _cancel(db, rid, "U_SOLO", client=client)

    # only the employee's own result DM, no manager FYI
    assert {c["channel"] for c in client.chat_postMessage_calls} == {"U_SOLO"}


# --- open_cancel_modal -----------------------------------------------------

def test_cancel_modal_lists_pending_and_future_approved_only(db):
    _people(db)
    pending = create_request(db, "U_ALICE", "sick", FUTURE_START, FUTURE_END, None)
    approved_future = _approved_future(db)
    past = create_request(db, "U_ALICE", "vacation", date(2026, 6, 1), date(2026, 6, 2), None)
    approve_request(db, past)
    declined = create_request(db, "U_ALICE", "personal", FUTURE_START, FUTURE_END, None)
    decline_request(db, declined, None)

    client, ack = FakeSlackClient(), FakeAck()
    open_cancel_modal(
        ack=ack, body={"user_id": "U_ALICE", "trigger_id": "T"}, client=client, db=db, today=TODAY
    )

    assert ack.response is None
    view = client.views_open_calls[0]["view"]
    options = view["blocks"][0]["element"]["options"]
    assert view["blocks"][0]["element"]["type"] == "static_select"
    assert {o["value"] for o in options} == {str(pending), str(approved_future)}


def test_cancel_modal_handles_more_than_ten_requests(db):
    # A backlog of >10 cancellable requests must still render (radio_buttons caps at
    # 10; static_select does not) so /dayoff-cancel doesn't fail to open.
    _people(db)
    for i in range(12):
        create_request(db, "U_ALICE", "vacation", date(2026, 7, i + 1), date(2026, 7, i + 1), None)

    client, ack = FakeSlackClient(), FakeAck()
    open_cancel_modal(
        ack=ack, body={"user_id": "U_ALICE", "trigger_id": "T"}, client=client, db=db, today=TODAY
    )

    element = client.views_open_calls[0]["view"]["blocks"][0]["element"]
    assert element["type"] == "static_select"
    assert len(element["options"]) == 12


def test_cancel_modal_empty(db):
    _people(db)
    client, ack = FakeSlackClient(), FakeAck()
    open_cancel_modal(
        ack=ack, body={"user_id": "U_ALICE", "trigger_id": "T"}, client=client, db=db, today=TODAY
    )
    assert ack.response == NOTHING_TO_CANCEL
    assert client.views_open_calls == []
