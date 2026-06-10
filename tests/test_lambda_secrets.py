"""The Lambda cold-start secrets bootstrap (#19): on first invocation it pulls the
Slack tokens and the Google service-account JSON out of SSM SecureString parameters
— named by non-secret env vars — and lands them where `build_app()` and
`CalendarClient.from_env()` look. Fully offline under moto; no live AWS or Slack.
"""

import json
import os
import time

import boto3
import pytest
from moto import mock_aws
from slack_sdk.signature import SignatureVerifier

import app
import lambda_handler
from lambda_handler import (
    BOT_TOKEN_PARAM_ENV,
    GOOGLE_SA_PARAM_ENV,
    SIGNING_SECRET_PARAM_ENV,
    load_secrets_from_ssm,
)
from tests.fakes import FakeCalendar

SA_JSON = json.dumps({"type": "service_account", "project_id": "demo"})


@pytest.fixture
def ssm_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv(BOT_TOKEN_PARAM_ENV, "/leave-bot/slack-bot-token")
    monkeypatch.setenv(SIGNING_SECRET_PARAM_ENV, "/leave-bot/slack-signing-secret")
    monkeypatch.setenv(GOOGLE_SA_PARAM_ENV, "/leave-bot/google-service-account")
    sa_file = tmp_path / "service-account.json"
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(sa_file))
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)
    return sa_file


def _seed_params(region="us-east-1"):
    ssm = boto3.client("ssm", region_name=region)
    ssm.put_parameter(Name="/leave-bot/slack-bot-token", Value="xoxb-real", Type="SecureString")
    ssm.put_parameter(
        Name="/leave-bot/slack-signing-secret", Value="signing-real", Type="SecureString"
    )
    ssm.put_parameter(
        Name="/leave-bot/google-service-account", Value=SA_JSON, Type="SecureString"
    )


def test_bootstrap_populates_env_and_writes_google_json(ssm_env):
    with mock_aws():
        _seed_params()
        load_secrets_from_ssm()

    assert os.environ["SLACK_BOT_TOKEN"] == "xoxb-real"
    assert os.environ["SLACK_SIGNING_SECRET"] == "signing-real"
    assert ssm_env.read_text() == SA_JSON
    assert os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"] == str(ssm_env)


class _Ctx:
    function_name = "leave-bot"
    invoked_function_arn = "arn:aws:lambda:us-east-1:0:function:leave-bot"


def _url_verification_event(signing_secret):
    body = json.dumps({"type": "url_verification", "challenge": "abc123"})
    timestamp = str(int(time.time()))
    signature = SignatureVerifier(signing_secret).generate_signature(
        timestamp=timestamp, body=body
    )
    return {
        "requestContext": {"http": {"method": "POST"}},
        "headers": {
            "content-type": "application/json",
            "x-slack-signature": signature,
            "x-slack-request-timestamp": timestamp,
        },
        "body": body,
        "isBase64Encoded": False,
    }


def test_handler_runs_bootstrap_lazily_once(ssm_env, monkeypatch):
    monkeypatch.setattr(lambda_handler, "_handler", None)
    monkeypatch.setattr(lambda_handler, "_secrets_loaded", False)
    # The handler builds the real app; stub the Google client so the test stays
    # about the lazy-bootstrap wiring, not Google service-account auth.
    monkeypatch.setattr(app.CalendarClient, "from_env", staticmethod(FakeCalendar))
    calls = []
    real = lambda_handler.load_secrets_from_ssm
    monkeypatch.setattr(
        lambda_handler, "load_secrets_from_ssm", lambda: calls.append(1) or real()
    )

    with mock_aws():
        _seed_params()
        # Signing secret lives in SSM ("signing-real"); sign the event with it so
        # the bootstrap-populated secret is what verifies the request.
        event = _url_verification_event("signing-real")
        first = lambda_handler.handler(event, _Ctx())
        lambda_handler.handler(_url_verification_event("signing-real"), _Ctx())

    assert first["statusCode"] == 200
    assert json.loads(first["body"])["challenge"] == "abc123"
    assert os.environ["SLACK_BOT_TOKEN"] == "xoxb-real"
    assert calls == [1]  # fetched once, then reused warm
