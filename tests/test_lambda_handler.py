"""The HTTP-mode (AWS Lambda) wiring: the Bolt app factory builds in both modes,
and the SlackRequestHandler verifies request signatures. All offline — no AWS, no
real Slack (a url_verification challenge is answered locally by Bolt).
"""

import json
import time

import pytest
from slack_bolt.adapter.aws_lambda import SlackRequestHandler
from slack_sdk.signature import SignatureVerifier

from app import build_app
from tests.fakes import FakeCalendar

SIGNING_SECRET = "test-signing-secret"


@pytest.fixture(autouse=True)
def _slack_env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SIGNING_SECRET)


class _Ctx:
    function_name = "leave-bot"
    invoked_function_arn = "arn:aws:lambda:us-east-1:0:function:leave-bot"


def _event(body, signature=None, timestamp=None):
    timestamp = timestamp or str(int(time.time()))
    if signature is None:
        signature = SignatureVerifier(SIGNING_SECRET).generate_signature(
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


def test_build_app_constructs_in_both_modes():
    assert build_app(calendar=FakeCalendar(), faas=False) is not None
    faas_app = build_app(calendar=FakeCalendar(), faas=True)
    assert faas_app.process_before_response is True


def test_signed_request_is_accepted():
    handler = SlackRequestHandler(app=build_app(calendar=FakeCalendar(), faas=True))
    body = json.dumps({"type": "url_verification", "challenge": "abc123"})

    resp = handler.handle(_event(body), _Ctx())

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["challenge"] == "abc123"


def test_bad_signature_is_rejected():
    handler = SlackRequestHandler(app=build_app(calendar=FakeCalendar(), faas=True))
    body = json.dumps({"type": "url_verification", "challenge": "abc123"})

    resp = handler.handle(_event(body, signature="v0=deadbeef"), _Ctx())

    assert resp["statusCode"] == 401


def test_lambda_handler_is_importable():
    from lambda_handler import handler

    assert callable(handler)
