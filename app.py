"""Entrypoint: build the Bolt app and run it over Socket Mode."""

import os

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from leave import db
from leave.blocks import LEAVE_CALLBACK_ID
from leave.handlers import open_leave_modal, submit_leave

load_dotenv()


def build_app():
    app = App(token=os.environ["SLACK_BOT_TOKEN"])

    @app.command("/leave")
    def _open(ack, body, client):
        with db.connect() as conn:
            open_leave_modal(ack, body, client, conn)

    @app.view(LEAVE_CALLBACK_ID)
    def _submit(ack, body, view):
        with db.connect() as conn:
            submit_leave(ack, body, view, conn)

    return app


def main():
    app = build_app()
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


if __name__ == "__main__":
    main()
