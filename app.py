"""Entrypoint: build the Bolt app and run it over Socket Mode."""

import os

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from leave.blocks import LEAVE_CALLBACK_ID
from leave.handlers import open_leave_modal, submit_leave

load_dotenv()


def build_app():
    app = App(token=os.environ["SLACK_BOT_TOKEN"])
    app.command("/leave")(open_leave_modal)
    app.view(LEAVE_CALLBACK_ID)(submit_leave)
    return app


def main():
    app = build_app()
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


if __name__ == "__main__":
    main()
