"""AWS Lambda entrypoint (Slack HTTP mode). Deploy this `handler` behind a
Lambda Function URL and point the Slack app's Request/Interactivity URLs at it
— see issue #17. Local development still uses Socket Mode via `python app.py`.
"""

from slack_bolt.adapter.aws_lambda import SlackRequestHandler

from app import build_app

_handler = None


def handler(event, context):
    # Built once on the first invocation and reused across warm invocations.
    global _handler
    if _handler is None:
        _handler = SlackRequestHandler(app=build_app(faas=True))
    return _handler.handle(event, context)
