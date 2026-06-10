"""AWS Lambda entrypoint (Slack HTTP mode). Deploy this `handler` behind a
Lambda Function URL and point the Slack app's Request/Interactivity URLs at it
— see issue #17. Local development still uses Socket Mode via `python app.py`.

On the first invocation the secrets are loaded from SSM SecureString parameters
(#19) before the Bolt app is built, so no plaintext secrets live in the Lambda's
environment configuration. The Socket Mode entrypoint never calls `handler`, so
it never triggers the fetch.
"""

import os

import boto3
from slack_bolt.adapter.aws_lambda import SlackRequestHandler

from app import build_app

# Non-secret env vars naming the three SSM SecureString parameters. The Terraform
# module (#20) sets these; the live secret values are set out-of-band (#17).
BOT_TOKEN_PARAM_ENV = "SLACK_BOT_TOKEN_PARAM"
SIGNING_SECRET_PARAM_ENV = "SLACK_SIGNING_SECRET_PARAM"
GOOGLE_SA_PARAM_ENV = "GOOGLE_SERVICE_ACCOUNT_PARAM"

DEFAULT_SERVICE_ACCOUNT_FILE = "/tmp/service-account.json"

_handler = None
_secrets_loaded = False


def _fetch(ssm, param_name):
    return ssm.get_parameter(Name=param_name, WithDecryption=True)["Parameter"]["Value"]


def load_secrets_from_ssm():
    """Fetch the Slack tokens and Google service-account JSON from SSM and place
    them where the app expects: the Slack creds in the process environment (read
    by `build_app()`), the Google JSON in a file on disk (read by
    `CalendarClient.from_env()` via `GOOGLE_SERVICE_ACCOUNT_FILE`)."""
    ssm = boto3.client("ssm", region_name=os.environ.get("AWS_REGION"))

    os.environ["SLACK_BOT_TOKEN"] = _fetch(ssm, os.environ[BOT_TOKEN_PARAM_ENV])
    os.environ["SLACK_SIGNING_SECRET"] = _fetch(ssm, os.environ[SIGNING_SECRET_PARAM_ENV])

    sa_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", DEFAULT_SERVICE_ACCOUNT_FILE)
    with open(sa_file, "w") as f:
        f.write(_fetch(ssm, os.environ[GOOGLE_SA_PARAM_ENV]))
    os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"] = sa_file


def handler(event, context):
    # Secrets load and the app builds once on the first invocation, reused warm.
    global _handler, _secrets_loaded
    if not _secrets_loaded:
        load_secrets_from_ssm()
        _secrets_loaded = True
    if _handler is None:
        _handler = SlackRequestHandler(app=build_app(faas=True))
    return _handler.handle(event, context)
