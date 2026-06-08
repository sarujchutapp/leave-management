"""Leave request persistence and the derived-balance query."""

from datetime import date

from leave.balance import count_weekdays


def approved_weekdays_this_year(conn, employee_id, leave_type, today):
    """Sum of weekdays across this employee's approved requests of this type
    whose start_date falls in the current calendar year."""
    year_start = date(today.year, 1, 1)
    year_end = date(today.year, 12, 31)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT start_date, end_date FROM requests
               WHERE employee_id = %s AND leave_type = %s AND status = 'approved'
                 AND start_date BETWEEN %s AND %s""",
            (employee_id, leave_type, year_start, year_end),
        )
        rows = cur.fetchall()
    return sum(count_weekdays(r["start_date"], r["end_date"]) for r in rows)


def remaining_balance(conn, employee, leave_type, today):
    """Derived, never stored: allowance minus approved weekdays this year."""
    allowance = employee["allowances"][leave_type]
    used = approved_weekdays_this_year(conn, employee["slack_user_id"], leave_type, today)
    return allowance - used


def has_overlap(conn, employee_id, start, end):
    """True if the range overlaps any of the employee's pending/approved requests."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM requests
               WHERE employee_id = %s AND status IN ('pending', 'approved')
                 AND start_date <= %s AND end_date >= %s
               LIMIT 1""",
            (employee_id, end, start),
        )
        return cur.fetchone() is not None


def create_request(conn, employee_id, leave_type, start, end, reason):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO requests (employee_id, leave_type, start_date, end_date, reason)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (employee_id, leave_type, start, end, reason),
        )
        return cur.fetchone()["id"]


def get_request(conn, request_id):
    return conn.execute("SELECT * FROM requests WHERE id = %s", (request_id,)).fetchone()


def approve_request(conn, request_id):
    conn.execute(
        "UPDATE requests SET status='approved', updated_at=now() WHERE id=%s", (request_id,)
    )


def decline_request(conn, request_id, reason):
    conn.execute(
        "UPDATE requests SET status='declined', decline_reason=%s, updated_at=now() WHERE id=%s",
        (reason, request_id),
    )


def set_calendar_event_id(conn, request_id, event_id):
    conn.execute(
        "UPDATE requests SET calendar_event_id=%s WHERE id=%s", (event_id, request_id)
    )


def cancellable_requests(conn, employee_id, today):
    """The employee's requests that can still be cancelled: any pending one, or
    an approved one that hasn't started yet."""
    return conn.execute(
        """SELECT id, leave_type, start_date, end_date, status FROM requests
           WHERE employee_id = %s
             AND (status = 'pending' OR (status = 'approved' AND start_date > %s))
           ORDER BY start_date""",
        (employee_id, today),
    ).fetchall()


def can_cancel(request, today):
    if request["status"] == "pending":
        return True
    return request["status"] == "approved" and request["start_date"] > today


def cancel_request(conn, request_id):
    conn.execute(
        "UPDATE requests SET status='cancelled', updated_at=now() WHERE id=%s", (request_id,)
    )
