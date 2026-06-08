"""Test fixtures. Each test gets an isolated `leave_test` schema on the real
Postgres so it never touches the live `public` data the bot uses.
"""

import os

import psycopg
import pytest
from dotenv import load_dotenv
from psycopg.rows import dict_row

from leave.seed import apply_schema

TEST_SCHEMA = "leave_test"


@pytest.fixture
def conn():
    load_dotenv()
    c = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, autocommit=True)
    c.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
    c.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
    c.execute(f"SET search_path TO {TEST_SCHEMA}")
    apply_schema(c)
    try:
        yield c
    finally:
        c.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
        c.close()
