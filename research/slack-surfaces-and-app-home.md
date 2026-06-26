# Slack surfaces, cost, and the App Home tab

How the Slack-native leave-tool category integrates with Slack, how that compares to our
slash-command design, what adopting the **Events API / App Home tab** actually costs us on
Lambda, and a spec for building it. Companion to [next-level-features.md](next-level-features.md)
and [coldstart-mitigation.md](coldstart-mitigation.md); touches [ADR-0002](../docs/adr/0002-aws-lambda-http-mode.md)
and [ADR-0007](../docs/adr/0007-keep-warm-ping.md).

## TL;DR

- The category (Flamingo, Vacation Tracker, …) all run the **same stack**, forced by being
  multi-tenant SaaS: **HTTP + Events API + OAuth, always-on**. We already match them on
  transport (HTTP); we differ in being single-tenant and serverless.
- Their primary surfaces are an **App Home tab** (discoverable dashboard) + slash commands /
  shortcuts (quick actions) + modals + bot DMs + a **web dashboard** for heavy views.
- We've built the quick-action layer well (slash + modal + interactive approvals + DMs). Our
  biggest gap is the **App Home tab** — a discoverable home base. Our slash commands are
  invisible: you must *know* `/dayoff` exists.
- Adopting App Home needs **no new AWS permission** — it's Slack-side (Events API) + a
  `views.publish` over the bot token we already have.
- **Cost:** Lambda is free-tier ($0). DynamoDB is the layer that actually bills (per read/write,
  no on-demand free tier) — and *rendering live data on open is a read*. A **static command center
  (buttons only)** reads nothing on open and bills only per-action; a **live dashboard** reads on
  open (pennies). Both are pennies-to-$0 at our scale — the choice is UX/purity, not money.
- It's the highest-leverage, IAM-free way to feel like the commercial tools. The lift is the
  Events API adoption (a one-line reversal of ADR-0002 → its own ADR) + a published view.

## How the category integrates with Slack

One fact dictates their architecture: they are **multi-tenant SaaS distributed on the Slack
Marketplace**, installed per workspace via **OAuth**. That forces:

- **HTTP (Request URL) mode + Events API** — *not* Socket Mode. Socket Mode needs a per-app
  persistent socket and can't fan out to thousands of customer workspaces.
- **Always-on web infrastructure** (horizontally scaled) — so cold starts aren't a concern for
  them; they pay for it and bill it through the subscription.

On top of that transport they use a *mix* of surfaces:

- **Flamingo — App Home–first.** The primary way to request leave is the **App Home tab**: open
  the app in the sidebar, pick dates/type/notes, submit; it also shows balance and lets you
  delete future requests. Slash commands (`/flamingo …`, `/flamingo help`) are secondary. Plus a
  web dashboard.
- **Vacation Tracker — slash + modal–first.** Primary is `/vacation` / `/request leave` → a
  **modal**; a **global shortcut** ("Request leave") is another entry; bot **DMs** carry
  approvals + daily/weekly digests; a **web dashboard** holds reports/calendars/admin. Pitch:
  "no one ever needs to leave Slack."

**Category pattern:** App Home (discoverable home) · slash command / shortcut (quick action) ·
modal (the form) · bot DM (approvals/notifications) · web app (heavy views).

## How we compare

| Dimension | Flamingo / Vacation Tracker | Us |
|---|---|---|
| Transport | HTTP + Events API | **HTTP (Lambda Function URL)** — same |
| Install | OAuth, multi-tenant (Marketplace) | Single internal workspace |
| Hosting | Always-on SaaS (no cold starts) | Serverless scale-to-zero (cold-start message) |
| Request surface | App Home and/or slash + modal + shortcut | **Slash + modal** (`/dayoff`) |
| Approvals | Interactive bot DM, 1-click | **Interactive ticket** — same |
| Home / dashboard | **App Home tab** + web dashboard | **None** (CSV + Google Sheet for views) |
| Shortcuts | Global shortcut entry point | None |

We match on transport and the quick-action layer. We diverge in: **no App Home** (discoverability
gap), **no web app** (CSV + Sheet instead), and **single-tenant + serverless** (deliberate — it's
what buys us scale-to-zero / ~$0; they can't be serverless or Socket Mode as distributed SaaS).

## Slash command vs App Home — the real design lever

- **Slash command (ours):** simplest to build, stateless, no Events API. Great when the user
  *knows what they want* ("book leave → `/dayoff`"). Costs: **discoverability** (must know it
  exists — new hires don't) and **no at-a-glance state** (balance/upcoming).
- **App Home (theirs):** discoverable home base in the sidebar, dashboard at a glance, the natural
  place to later host the burnout board + calendar. Costs: needs the **Events API**
  (`app_home_opened`) + `views.publish`, and a stateful view to (re)build.

## Cost: what App Home actually costs us

Two layers, and they behave differently — don't conflate them.

**Lambda — free.** Slack's Events API is free; each event/interaction is one invocation, and at a
5–20-person team's volume it's far inside the perpetual free tier (1M requests + 400k GB-s). **$0.**
(Only chatty subscriptions like `message.channels` would change that — we subscribe to
`app_home_opened` only, so volume is bounded.)

**DynamoDB — the layer that actually bills.** On-demand (`PAY_PER_REQUEST`) charges **per operation
— every read *and* every write** (~$0.13 per *million* read units), and on-demand gets **no
free-request tier** (the 25-RCU free tier is provisioned-mode only). So this is the layer to reason
about for pay-per-usage purity.

The trap: **viewing your own data is a database read.** A tab that shows your balance + leave isn't
a no-op on open — the app must *read* that data to render it, and DynamoDB bills reads, not just
writes/actions:

- `/dayoff` opening a modal → reads your balances to show them → billed (we pay this today).
- App Home open *that renders live data* → reads → billed.
- Keep-warm ping → renders nothing, reads nothing → genuinely $0.

So App Home, *if it renders a live dashboard*, shifts DB reads from **per-action** to **per-view**
(people glance more than they act; `app_home_opened` can re-fire) — strictly more reads than
slash-only.

**The design lever — command center vs dashboard.** That per-*open* read cost exists ONLY if the
home renders live data. Make the home a **static command center (labeled buttons, no personalized
data)** and opening it reads nothing — you touch the DB only when a button is *clicked*
(per-action, same as a slash command):

| Home style | On open | On click | At-a-glance |
|---|---|---|---|
| **Static command center** (buttons only) | **$0** — no DB read | per-action (DB as needed) | low — click to see anything |
| **Data dashboard** (balance/leave shown) | DB reads (pennies) | per-action | high — see everything at once |

A static command center is *more* pay-per-usage-pure than even the slash-command setup (nothing
happens until you press something) and still beats invisible commands on discoverability. The trade
is **UX, not money**: it doesn't *show* your balance until you click "My balance".

**Bottom line:** at our scale every option is pennies-to-$0, so cost isn't a real differentiator —
the trade-offs are UX (glance vs click), purity (per-view vs per-action), and one-time setup (Events
API + an ADR). But if pay-per-usage purity is the pitch, the **static command center keeps opens
free and bills only on action** — the cleanest fit.

## Why we didn't use the Events API originally

Slack has **three separate inbound channels**: slash commands (each command's Request URL),
interactivity (buttons/modals — one Request URL), and **Event Subscriptions** (passive workspace
events — a separate Request URL). Every original interaction is **user-initiated** — `/dayoff`,
Approve, submit a modal — which flow through the *slash-command* and *interactivity* channels, not
the Events API. There was simply no passive event to listen for, so [ADR-0002](../docs/adr/0002-aws-lambda-http-mode.md)
left Event Subscriptions off, which:

- kept the app config and processing surface **minimal**, and
- kept Lambda invocations tied to **actual user actions** (no passive background traffic) — fitting
  the pay-per-usage philosophy.

**App Home is the first feature that genuinely requires events** — there's no way to know a user
opened their Home tab except `app_home_opened`. That's why enabling it now is a deliberate change
(its own ADR), and why we subscribe to that one event only.

## Cold-start interaction

- `app_home_opened` is **gentler** on cold start than a slash command: a slow ack just makes Slack
  *retry* (idempotent re-publish), **not** a user-facing `operation_timeout`. So App Home doesn't
  reintroduce the visible cold-start message for *opening* the tab.
- **But** the Home's "Request leave" button still opens a **modal** → same `trigger_id`/3s
  cold-start risk as `/dayoff`. The parked keep-warm ping (ADR-0007) would cover it; not a blocker.

## App Home spec — what we need

**Slack app config** (Slack-app owner; no AWS):
- App Home → Home Tab **on**.
- Event Subscriptions **on** → Request URL = existing Function URL → subscribe to bot event
  **`app_home_opened`** (Bolt answers the `url_verification` challenge automatically).
- **Reinstall** the app if Slack prompts (events/Home change). Verify no new OAuth scope is demanded
  (`views.publish` uses the existing bot token); reinstall if one is added.

**Code** (no new table, no new AWS IAM):
- `build_home_view(...)` in `blocks.py`.
- `publish_home(client, db, user_id, today)` in `handlers.py` → `client.views_publish(user_id, view)`.
- `app.event("app_home_opened")` in `app.py` — faas: ack fast + **lazy** publish (no `trigger_id`
  needed, so post-ack is safe); inline for Socket Mode.
- Wire Home buttons to **existing** flows: Request leave → `build_leave_modal`; Cancel →
  `build_cancel_modal`; Plan a break → `/advance`; managers → the `/burnout` modal.
- Add `views_publish` to `FakeSlackClient` for tests.

**Docs:** a new ADR — adopting the Events API **amends ADR-0002**'s "slash commands + interactivity
only, Events off" line.

**Deploy:** existing `./build.sh && terraform apply` (no terraform change, no new perms). Only manual
step is the Slack config above.

**Content design — two flavours (decide up front, it shapes the cost):**

*Static command center* (recommended for pay-per-usage purity) — buttons only, **no DB read on
open**:
```
🏖  Leave
 [ Request leave ]   [ Cancel a request ]
 [ Plan a break ]    [ My balance ]
```
Opening reads nothing; each button reads only what its action needs (per-action, like a slash
command). Publish a static view on `app_home_opened` (or once) and no-op repeat opens.

*Live dashboard* (the Flamingo/Vacation-Tracker feel) — renders personal data on open (reads DB,
pennies):
```
🏖  Your Leave
Hi Alice! Here's where you stand.
 Vacation: 7 left   ·   Sick: 28   ·   Personal: 5
 [ Request leave ]   [ Plan a break ]
```

**Expansion (either flavour):** upcoming/recent leave + [ Cancel a request ]; managers →
[ Burnout board ]; admins → [ Admin controls ]; not-registered user → a "contact your admin" card.
A live dashboard is rebuilt from live data on each open (nothing new to persist); a command center
publishes a static view and fetches only on click.

**Slices (tracer-bullet, TDD):**
1. `app_home_opened` → publish balances + a "Request leave" button that opens the existing modal
   (proves Events wiring → publish → interaction end-to-end).
2. Upcoming/recent leave + Cancel.
3. Plan-a-break + manager Burnout-board entry.
4. Admin entry + not-registered case.

**Decisions & risks:**
- **ADR for Events API** — the one real architectural shift (ADR-0002 deliberately avoided events).
- Cold start is gentler here, but the Home "Request leave" button shares `/dayoff`'s modal cold-start
  risk (keep-warm parked).
- **Reinstall** on enabling events — one-time HITL.
- **Scope creep** — v1 = balances + Request button only; resist the full dashboard at once.

## Verdict

App Home is the **highest-leverage, AWS-permission-free** way to close the biggest gap with
Flamingo / Vacation Tracker — a discoverable home base instead of "a bot you must know the commands
for." It's a bigger lift than a slash-command feature (Events API + a published view + an ADR), but
cost is not a reason to hesitate ($0–pennies either way). The decision is: is the discoverability
worth the one-time Events-API setup — and if so, **static command center or live dashboard?**

Recommended starting point: a **static command center** — it's the cheapest (free opens, per-action
billing), the simplest to build (no per-user data assembly on open), and the most on-brand for the
pay-per-usage pitch, while still giving the discoverable, labeled home that slash commands lack. A
live dashboard can come later if the at-a-glance balance proves worth the per-open reads.

## Sources

- [Vacation Tracker Slackbot Guide](https://vacationtracker.io/blog/vacation-tracker-slackbot-guide/) ·
  [Vacation Tracker on Slack Marketplace](https://slack.com/apps/A1L3ZBM7G-vacation-tracker)
- [Flamingo Quick Start Guide](https://support.flamingoapp.com/article/60-quick-start-guide-for-users) ·
  [Flamingo](https://flamingoapp.com/) ·
  [Flamingo on Slack Marketplace](https://slack.com/marketplace/A01MLSHLQHY-leave-management-by-flamingo)
- [Slack: implementing shortcuts](https://docs.slack.dev/interactivity/implementing-shortcuts/)
