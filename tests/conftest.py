"""Test fixtures. Each test gets a fully offline DynamoDB via moto (`mock_aws`):
both tables + the `by_employee` GSI are provisioned per test, so nothing touches
a real AWS account and no credentials or `DATABASE_URL` are needed.
"""

import pytest
from moto import mock_aws

from leave.db import connect
from leave.seed import create_tables


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        create_tables()
        yield connect()
