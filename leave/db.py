"""Database connection and employee lookup."""

import os

import psycopg
from psycopg.rows import dict_row


def connect():
    """A real connection against DATABASE_URL, rows as dicts."""
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def get_employee(conn, slack_user_id):
    """Return the employee row (dict) or None if not registered."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slack_user_id, real_name, manager_id, allowances "
            "FROM employees WHERE slack_user_id = %s",
            (slack_user_id,),
        )
        return cur.fetchone()
