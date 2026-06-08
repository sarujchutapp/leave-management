# Setup

One-time provisioning of the three external resources, then a smoke check. All steps here are manual dashboard work; when done you fill in `.env` and run `python smoke_check.py`.

## 1. Slack app

1. Go to https://api.slack.com/apps → **Create New App** → From scratch. Pick your personal test workspace.
2. **Slash Commands** → Create New Command: command `/leave`, any request URL placeholder (Socket Mode ignores it), short description.
3. **Socket Mode** → toggle on. When prompted, generate an **App-Level Token** with scope `connections:write` → copy it (`xapp-...`) into `SLACK_APP_TOKEN`.
4. **Interactivity & Shortcuts** → toggle on (URL is ignored under Socket Mode).
5. **OAuth & Permissions** → Bot Token Scopes → add `chat:write` and `commands`. (Modals and DMs are covered by these.)
6. **Install App** to the workspace → copy the **Bot User OAuth Token** (`xoxb-...`) into `SLACK_BOT_TOKEN`.

## 2. Postgres

1. Create a free project on [Supabase](https://supabase.com) or [Neon](https://neon.tech).
2. Copy the connection string into `DATABASE_URL`. (Supabase: Project Settings → Database → Connection string, URI form. Neon: dashboard connection string.)

## 3. Google Calendar + service account

1. With your **personal Gmail**, open Google Calendar → create a new calendar named **Team Leave**.
2. Go to https://console.cloud.google.com → create a project → **APIs & Services → Enable APIs** → enable **Google Calendar API**.
3. **APIs & Services → Credentials → Create credentials → Service account**. After creating, open it → **Keys → Add key → JSON** → download. Save it in this repo as `service-account.json` (gitignored). Note the service account's email (`...@...iam.gserviceaccount.com`).
4. Back in Google Calendar → Team Leave → **Settings and sharing → Share with specific people** → add the service account email with **"Make changes to events"**.
5. Same settings page → **Integrate calendar → Calendar ID** → copy into `TEAM_CALENDAR_ID`.

## 4. Configure and verify

1. `cp .env.example .env` and fill in every value.
2. `python -m venv .venv && .venv\Scripts\activate` (Windows PowerShell) then `pip install -r requirements.txt`.
3. `python smoke_check.py` — expect `PASS` on all three. The calendar check creates and immediately deletes a throwaway event tomorrow.
