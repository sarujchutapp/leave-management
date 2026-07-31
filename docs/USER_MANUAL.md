# Leave Management — User Manual

| | |
|---|---|
| **Product** | Leave Management (Slack leave bot) |
| **Document type** | User manual (how to use the bot in Slack) |
| **Audience** | Employees, managers, and the admin |
| **Last updated** | 2026-07-31 |
| **Author** | Saruj Chutapornpong |

> This manual covers **using** the bot from Slack. It is deliberately not technical.
>
> - How the system is built → [`SOFTWARE_DOCUMENTATION.md`](SOFTWARE_DOCUMENTATION.md)
> - How to install and deploy it → [`SETUP.md`](../SETUP.md)
> - What the domain words mean, precisely → [`CONTEXT.md`](../CONTEXT.md)

---

## 1. Before you start

Everything happens inside Slack. There is no website to log in to and no app to install.

Three things to know first:

1. **Someone has to add you.** You can't sign yourself up. If the bot replies
   *"You're not set up in the leave system yet — please contact your admin."*, ask your admin
   to add you (§5.7).
2. **Everything is a direct message.** The bot talks to you in your DM with it. Nothing is
   posted to a public channel, except a link to the shared leave sheet (§6.2).
3. **You can run the commands anywhere.** Type them in any Slack channel or DM — the reply is
   private to you either way.

---

## 2. Quick reference

| Command | Who can use it | What it does |
|---|---|---|
| `/dayoff` | Everyone | Request time off. |
| `/dayoff-cancel` | Everyone | Cancel a leave you haven't taken yet, or come back early from one you're on. |
| `/advance` | Everyone | Suggests the best breaks you could still take, and finds a window a group can all take off together. |
| `/burnout` | Managers | A board of your direct reports ranked by how long it's been since each took time off. |
| `/control` | The admin only | Company settings: allowances, carry-over, holidays, employees, reports, and a full reset. |

Three kinds of leave exist: **sick**, **vacation**, and **personal**. Each has its own
separate balance.

---

## 3. For employees

### 3.1 Requesting time off — `/dayoff`

Type `/dayoff` and press Enter. A window titled **Request Leave** opens.

At the top you'll see a line like `Days left — sick: 8 · vacation: 12.5 · personal: 3`.
That's your current balance for each type.

Fill in the form:

| Field | Required | Notes |
|---|---|---|
| **Leave type** | Yes | Sick, Vacation, or Personal. |
| **Start date** | Yes | Pick from the calendar. |
| **End date** | No | *Leave empty for a single-day leave.* |
| **Half day?** | No | Defaults to **Full day**. Choose **Morning** or **Afternoon** to take half a day — this only works for a single day, so the end date must be empty. |
| **Reason** | No | Free text. Your manager sees it on the approval message. |

Press **Submit**.

If something's wrong, the window stays open with a red message under the offending field —
see §7.1 for what each one means. Fix it and submit again.

### 3.2 What happens after you submit

Two possible paths, depending on how your admin set you up:

**Path A — your leave approves itself.** You get a DM straight away:

> Your vacation leave 2026-08-10 → 2026-08-14 was auto-approved.

This is how people at the top of the chain work, and the admin can also switch it on for
anyone (the "auto" approval setting, §5.7).

**Path B — your manager decides.** The window just closes. Nothing is sent to you yet —
your manager gets a message with **Approve** and **Decline** buttons. When they act on it,
you get one of:

> Your vacation leave 2026-08-10 → 2026-08-14 was approved.

> Your vacation leave 2026-08-10 → 2026-08-14 was declined. Reason: two people already out that week.

The decline reason only appears if your manager wrote one.

**While you're waiting**, the days are already set aside. Your balance goes down as soon as
you submit, not when it's approved — so you can't accidentally book the same days twice by
submitting two requests. If the request is declined or you cancel it, the days come back.

To check on a request you're waiting on, run `/dayoff` — the "Days left" line reflects
everything pending and approved. Or run `/dayoff-cancel`, which lists your requests with
their status (you can back out without cancelling anything).

### 3.3 How days are counted

- **Weekends don't count.** A Friday-to-Monday leave uses 2 days, not 4.
- **Company holidays don't count** either.
- **A half day counts as 0.5.**
- **Vacation left over rolls into next year**, up to a cap the admin sets. Sick and personal
  start fresh each leave year and don't roll over.
- **The leave year doesn't have to start in January.** The admin sets a reset date; your
  balance refreshes then.

Because days are counted fresh every time rather than stored as a running total, adding a
holiday later automatically refunds any leave that overlapped it.

### 3.4 Cancelling, or coming back early — `/dayoff-cancel`

Type `/dayoff-cancel`. A window titled **Cancel Leave** opens with a dropdown of your
requests, earliest first, each labelled with its type, dates, and status — for example:

```
vacation · 2026-08-10 → 2026-08-14 (pending)
sick · 2026-08-03 (approved)
personal · 2026-07-30 → 2026-08-02 (in progress)
```

Pick one and press **Cancel leave**.

**If the leave hasn't started yet** (or is still pending), it's cancelled outright. The
calendar event disappears, the leave board updates, and you get:

> Cancelled your vacation leave 2026-08-10 → 2026-08-14.

Your manager gets an FYI so they aren't left wondering.

**If you're currently on the leave** — marked `(in progress)` — cancelling means **coming
back early** instead. The days you've already taken, up to and including today, stay used.
Only the days you haven't taken are given back:

> Your personal leave ended early — kept through 2026-07-31, 2 day(s) returned to your balance.

Your manager gets an FYI with the new end date and how many days came back.

You cannot cancel leave that's already finished. Trying gives you
*"That request can no longer be cancelled."*

### 3.5 Planning a break — `/advance`

`/advance` does the arithmetic for you: given what you have left and what's already booked,
how long a break can you actually still take?

Type `/advance`. A window titled **Leave Optimizer** opens with up to three options,
deliberately different from each other rather than three versions of the same week:

```
🌴 Your best break options this year:

1. 9 days off · 5 days used (Aug 8–16)      [Book]
2. 5 days off · 3 days used (Sep 12–16)     [Book]
3. 4 days off · 2 days used (Oct 24–27)     [Book]
```

Read a line as: **days off** is how long you'd actually be away including the weekends and
holidays it leans on; **days used** is what comes out of your vacation balance; the dates in
brackets are what gets booked.

Press **Book** on any option and the normal Request Leave form opens with the type and dates
already filled in. You can still change anything before submitting — and it still goes
through the same checks and the same approval as any other request.

If there's nothing to suggest you'll see:

> No vacation break to suggest right now — you may be out of vacation balance, have days
> awaiting approval, or have no open stretch left this year.

### 3.6 Taking a break together — the group option

At the bottom of the `/advance` window is **👥 Plan a group break**.

Press it, pick the teammates you'd like to go with (you're always included, so you can also
just submit with nobody picked), and press **Find window**. The bot DMs you the longest
stretch where *everyone* picked could be off at the same time — each person still within
their own balance and limits:

> 👥 Longest window you can all be off together: 2026-10-12 to 2026-10-18 (7 days).
> Everyone books their own leave for these dates.

**Nobody's balance is revealed** — not yours to them, not theirs to you. You only see the
shared window. Share the dates with the group and each person books their own leave; the
**Book mine** button on the result books yours.

If there's no such window: *"No window found where everyone can be off together in the rest
of the year — try a smaller group or different people."* Try fewer people.

### 3.7 If you get a wellbeing nudge

You may occasionally receive a DM like:

> Hi! 🌿 Just a friendly wellbeing check-in — it's been *112 days* since your last time off.
> You also have *4* vacation day(s) that expire when your leave year resets. Taking a break
> is good for you. No pressure — but if you'd like to plan one, `/advance` can suggest the
> best windows. 🌴

This is sent when your manager presses **Nudge** on their burnout board. It's a prompt, not
a warning, and nothing is booked or recorded. You don't have to reply. If you'd like to act
on it, `/advance` is the fastest way.

---

## 4. For managers

You're a manager here if someone is listed with you as their approver. It's automatic — no
extra setup, and it's completely separate from being an admin.

### 4.1 Approving and declining

When one of your reports requests leave, you get a DM:

> **Ratchanon** requests **vacation** leave
> 2026-08-10 → 2026-08-14
>
> Balance left for vacation: 12
>
> Reason: family trip
>
> ⚠️ **Coverage check** — on 2026-08-12, 2 other peers are already off:
> ✅ Napat (approved)
> ⏳ Kanya (pending)
>
> [ **Approve** ] [ Decline ]

**Approve** puts the leave on the team calendar, updates the leave board, and tells the
employee. The buttons are replaced by a line recording what you decided.

**Decline** opens a small window asking for an optional **Reason**, then press **Decline**.
The employee is told, with your reason if you gave one.

Either way the message stops being clickable, so there's no risk of deciding twice.

### 4.2 The coverage check

That ⚠️ block appears only when other people who report to you already have overlapping
leave. It names them and marks whether each is **✅ approved** or **⏳ pending**.

It's information, not a rule — the bot never blocks an approval because of it. It's worth
reading because pending leave isn't visible on the shared board yet, so this catches clashes
a glance at the board would miss.

### 4.3 The burnout board — `/burnout`

Type `/burnout`. It takes a moment to build ("⏳ Building your burnout board…"), then shows
your direct reports, most at risk first:

```
🔴  #1 · Ratchanon
Days since last leave:  112
Vacation left:  14 days
Next break:  Nothing booked
[ 🌿 Nudge ]

🟠  #2 · Napat
Days since last leave:  56
Vacation left:  6 days
Next break:  Sep 14
[ 🌿 Nudge ]

Risk: 🔴 90+ days since last leave · 🟠 45+ · 🟢 under 45
[ 🔄 Refresh ]
```

**How to read it:**

- **Days since last leave** is counted backwards from today to the last leave they actually
  *took*. It's the main signal.
- **Next break** is leave they've already booked. A booked break counts as relief — it
  lowers the risk and never inflates the day count.
- The **coloured dot** is only a band on that same day count, spelled out in the legend at
  the bottom. There's no hidden score.
- **🔄 Refresh** rebuilds it — it's a live snapshot, not a saved report.

**🌿 Nudge** sends that person the supportive DM in §3.7. It comes from the bot, not from
you, and it books nothing. The button turns into **✓ Nudged** so you can see you've done it
(that marker only lasts as long as the window is open).

If you don't manage anyone: *"You don't manage anyone, so there's no burnout board to show."*

### 4.4 FYI messages you'll receive

Besides approval requests, the bot DMs you when:

- A report cancels leave you'd approved —
  *"FYI: Napat cancelled their vacation leave 2026-08-10 → 2026-08-14."*
- A report comes back early —
  *"FYI: Napat returned early from their personal leave — now 2026-07-28 → 2026-07-31 (2 day(s) returned)."*

Nothing is required of you; they're so the calendar doesn't change behind your back.

---

## 5. For the admin — `/control`

`/control` is limited to the people on the admin allowlist (currently one person). Anyone
else gets *"Sorry, /control is for admins only."*

Being an admin is unrelated to being a manager. It doesn't let you approve anyone's leave,
and managers don't get `/control`.

Type `/control` and you get **Admin Control** — a menu of seven buttons. Each opens its own
window; each finishes by closing the window and DMing you the result, so you always get
written confirmation of what changed.

### 5.1 View settings

Read-only summary of the current rules:

```
Allowances — sick: 10 · vacation: 15 · personal: 5
Max carry over (vacation): 5
Max total (vacation): 20
Consecutive limit (vacation): 15
```

Worth opening before you change anything.

### 5.2 Leave limits

Sets how many days a year everyone gets, plus the cap on how long a single stretch away can
be.

| Field | Meaning |
|---|---|
| **Sick / Vacation / Personal allowance (days)** | The yearly amount for everyone. |
| **Enforce a consecutive limit on vacation** | Untick to remove the cap entirely. |
| **Vacation consecutive limit (days)** | The longest continuous absence allowed, when the cap is on. Default 15. Weekends, holidays, and leave of any type all count towards the run — it's *days away*, not days of quota. |

Press **Save**. You get: *"✅ Leave limits updated — sick 10, vacation 15, personal 5,
consecutive 15."*

> **Read the warning in the window.** Lowering an allowance takes effect immediately, and
> anyone who has already used more than the new amount goes negative — which blocks their
> new bookings until the leave year resets. Raising it back fixes it.

The vacation allowance can't be set above **Max total** (§5.3); the window will tell you.

### 5.3 Carry-over

Controls unused vacation rolling into next year, and when the year turns over.

| Field | Meaning |
|---|---|
| **Enable carry-over** | Untick to switch it off — nothing rolls over. |
| **Max carry over (vacation days)** | The most that can roll *out* of a year. |
| **Max total (vacation days)** | The ceiling on what anyone can have available in one year (allowance + rolled-over days). |
| **Leave-year reset date (month & day; year ignored)** | Pick any date; only the month and day are used. This is when balances refresh. |

Press **Save**. You get: *"♻️ Carry-over caps saved and carry-in recomputed for 12
employee(s)."*

> Lowering a cap recalculates everyone's rolled-over days immediately — balances can drop
> and go negative, which blocks new bookings. Raising it back restores them.

The reset date only ever moves **forward** from today; you can't retroactively reopen a
period that's closed.

### 5.4 Holidays

Company holidays don't consume anyone's leave. One set applies to everyone.

Pick an **Action** at the top; the fields change to match:

- **Add a holiday** — a **Date** and a **Label**. → *"✅ Saved holiday 2026-12-31 — New Year's Eve."*
- **Remove a holiday** — pick from the list of current holidays. → *"🗑️ Removed holiday 2026-12-31."*
  Removing only affects today onwards.
- **Import holidays** — paste one per line as `date,label`:
  ```
  2026-04-13,Songkran
  2026-12-31,New Year's Eve
  ```
  → *"✅ Imported 14 holidays."* Import is all-or-nothing: if any line is malformed, nothing
  is saved and you're told which.

Holidays also appear on the shared calendar for visibility, but the calendar is only a
display — the stored list is what counts days.

### 5.5 Report

DMs you a CSV. Three choices:

- **All-employee quota** — everyone's allowance, used, and remaining per type.
- **One person's leave history** — every request for one person, whatever its status. Choosing
  this reveals a person picker.
- **Team burnout risk** — the fuller version of the manager board, across everyone, with
  extra flags such as days left in the period and long stretches of unbroken work. Every flag
  is explained in words rather than scored.

Press **Send**; the file arrives in your DM. Picking an app or bot as the person is rejected.

### 5.6 Clear

**Destructive.** Deletes **all** leave requests, removes their calendar events, and blanks the
leave board. Employees, policy, and holidays are kept.

You must type **`CLEAR`** exactly to confirm — anything else does nothing. Then:
*"🧹 Cleared 87 leave request(s), removed their calendar events, and reset the board."*

This cannot be undone. Anyone whose leave was pending or in progress is settled first, so no
approval message is left dangling.

### 5.7 Manage employees

Pick the **Employee** (a Slack person picker — their current details fill in automatically if
they're already in the system), then pick an **Action**:

**Add / edit**

| Field | Meaning |
|---|---|
| **Name** | How they appear in messages, on the board, and in reports. |
| **Manager** | Who approves their leave. *Pick the person themselves if they're top of chain.* |
| **Approval** | **auto** — their leave approves the moment they submit, no message to anyone. **approval-needed** — a request goes to their manager (or to themselves, if they're their own manager). |

→ *"✅ Saved Ratchanon (@ratchanon)."*

New people default to **approval-needed**. For someone already in the system, the box shows
what's currently in effect.

> **Changing someone's manager withdraws their pending requests.** They're told:
> *"Your manager is now @somchai. 2 pending request(s) were withdrawn — please re-file them
> so they reach the right approver."* Approved leave is untouched. This is deliberate — it
> stops a request sitting in the old manager's DMs where nobody will action it.

**Set allowance override**

Gives one person different yearly amounts from everyone else — a part-timer, say. Fill in
**Sick / Vacation / Personal override**; leave **all three blank** to clear the override and
put them back on the company policy.

→ *"✅ Allowance override set for @ratchanon."*

**Delete**

Removes the person from the leave system, cancels their leave, and withdraws any pending
requests (their manager sees *"This request was withdrawn — the employee was removed from the
leave system."*).

→ *"🗑️ Removed @ratchanon from the leave system."*

**Blocked while they still manage someone.** Reassign their reports first — otherwise those
people would have no approver.

---

## 6. Where your leave shows up

### 6.1 The team calendar

Approved leave becomes an all-day event on the shared Google "Team Leave" calendar, tinted
with a colour that stays the same for you, so the calendar is scannable at a glance.
Cancelling removes the event. Coming back early shortens it. Company holidays appear here
too.

Pending leave is **not** on the calendar — only approved.

### 6.2 The leave board

A Google Sheet laid out as a grid: people down the side, days of the month across the top,
coloured by leave type. The bot rebuilds it whenever leave is approved or cancelled and posts
a message with a **📋 Leave sheet** link to whichever Slack channel is configured for it.

Like the calendar, the board shows **approved leave only** — which is exactly why the
coverage check on the approval message (§4.2) exists.

---

## 7. When something doesn't work

### 7.1 Red messages in the Request Leave window

| Message | What it means | What to do |
|---|---|---|
| *End date can't be before the start date.* | The dates are the wrong way round. | Swap them. |
| *A half day must be a single date — leave the end date empty.* | You picked Morning or Afternoon along with an end date. | Clear the end date, or set Half day back to **Full day**. |
| *Start date can't be in the past.* | Backdating isn't allowed. | Pick today or later. Talk to your admin about leave you've already taken. |
| *That range has no working days — weekends and holidays don't use leave.* | Every date you picked is a weekend or holiday, so there'd be nothing to deduct. | You don't need to book these days at all. |
| *Not enough vacation balance: 5 requested, 3 left.* | You don't have the days — remember anything still awaiting approval is already reserved. | Shorten the request, cancel something pending, or use a different leave type. |
| *This overlaps one of your existing requests.* | You already have leave over some of those dates. | Check `/dayoff-cancel` to see what's there. |
| *This would be 18 consecutive days away; the limit is 15.* | Together with adjacent weekends, holidays, and other leave, the stretch away is too long. | Shorten it, or split it into two shorter breaks. |

### 7.2 Messages the bot DMs you

| Message | What it means |
|---|---|
| *You're not set up in the leave system yet — please contact your admin.* | You haven't been added. Only the admin can do it (§5.7). |
| *You have no requests to cancel.* | Nothing pending or upcoming. Past leave can't be cancelled. |
| *That request can no longer be cancelled.* | Already finished, already cancelled, or just decided by someone else. |
| *You're not the approver for this request.* | You pressed Approve or Decline on something that isn't yours to decide — usually a forwarded message, or the person's manager has since changed. |
| *Sorry, /control is for admins only.* | Working as intended. |
| *You don't manage anyone, so there's no burnout board to show.* | Nobody currently lists you as their approver. |
| *Pick real people — apps/bots can't take leave.* | Remove the app from your group-break selection. |
| *This request was withdrawn — …* | An admin removed the employee, or changed their manager, while this was pending. Nothing for you to do. |

### 7.3 Other things that come up

**A command does nothing, or Slack says it failed.** Try it once more. The bot sleeps when
it's unused and the very first command after a quiet spell can occasionally time out; the
second one lands.

**My balance looks wrong.** Two usual causes: pending leave is already deducted (§3.2), and
an admin may have changed an allowance or a carry-over cap (§5.2, §5.3) — which applies
immediately, and can push a balance negative for someone who'd already used more than the new
amount. `/control` → View settings shows the current numbers; the admin can DM themselves the
all-employee quota report to see the workings.

**A holiday was added after I booked leave over it.** You get those days back automatically —
no need to re-file.

**Approved leave isn't on the calendar or the board.** Both are rebuilt in the background a
moment after approval. If it's still missing after a few minutes, tell your admin — leave data
itself is stored separately and is never lost when the calendar or sheet fails to update.

**I need leave that breaks a rule** — backdated, over balance, or longer than the consecutive
limit. The bot has no override. Ask your admin, who can adjust the policy or your personal
allowance.

---

## 8. Common questions

**Do I need to tell my manager separately?**
No. The bot DMs them with the buttons. Courtesy is up to you.

**Can I edit a request after submitting?**
No — cancel it and file a new one. If it's still pending, cancelling costs you nothing.

**Can I book leave for someone else?**
No. Each person files their own. The group break finder (§3.6) finds shared dates, but
everyone still books their own.

**Who can see my reason?**
Whoever approves your request. It isn't on the calendar or the board.

**Does the bot decide anything about my leave?**
No. Every suggestion is plain arithmetic on data you already have, and every rule is one the
admin set and can see. The only automatic decision is auto-approval, which the admin turns on
per person (§5.7).

**Can I see my whole leave history?**
Not directly — ask your admin for the "One person's leave history" report (§5.5).

**What happens to my unused days at the end of the year?**
Unused **vacation** rolls over, up to the cap. **Sick** and **personal** don't. `/burnout`
flags expiring days for managers, and a nudge mentions them.
