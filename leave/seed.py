"""Schema application and proxy-data seeding.

Run `python -m leave.seed` to (re)create the schema and load proxy employees.
Replace the proxy Slack IDs with real ones (Slack profile -> Copy member ID)
to exercise the bot live.
"""

from pathlib import Path

from psycopg.types.json import Jsonb

from leave import db

DEFAULT_ALLOWANCES = {"sick": 30, "vacation": 10, "personal": 5}

_SCHEMA = Path(__file__).with_name("schema.sql").read_text()


def apply_schema(conn):
    # psycopg's execute() runs one statement at a time, so split the file.
    for statement in filter(str.strip, _SCHEMA.split(";")):
        conn.execute(statement)


def upsert_employee(conn, slack_user_id, real_name, manager_id=None, allowances=None):
    conn.execute(
        """
        INSERT INTO employees (slack_user_id, real_name, manager_id, allowances)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (slack_user_id) DO UPDATE
        SET real_name = EXCLUDED.real_name,
            manager_id = EXCLUDED.manager_id,
            allowances = EXCLUDED.allowances
        """,
        (slack_user_id, real_name, manager_id, Jsonb(allowances or DEFAULT_ALLOWANCES)),
    )


# Proxy employees for local testing. U_BOSS has no manager (top of chain).
PROXY_EMPLOYEES = [
    ("U_BOSS", "Boss Lady", None),
    ("U_ALICE", "Alice Employee", "U_BOSS"),
    ("U_BOB", "Bob Employee", "U_BOSS"),
]


def main():
    with db.connect() as conn:
        apply_schema(conn)
        for slack_user_id, real_name, manager_id in PROXY_EMPLOYEES:
            upsert_employee(conn, slack_user_id, real_name, manager_id)
        conn.commit()
        print(f"Seeded {len(PROXY_EMPLOYEES)} employees.")


if __name__ == "__main__":
    main()
