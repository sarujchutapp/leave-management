# 3: Nudge button -> supportive bot DM on /burnout

- Issue: #47
- Labels: ready-for-agent

---

## Parent

Burnout Board PRD: #44

## What to build

Add a **Nudge** button to each row of the `/burnout` board. When the manager
clicks it, the **bot** sends a supportive, wellbeing-framed direct message to that
report — naming the specific reason (their no-break stretch, and expiring days
when relevant) and pointing them to `/advance` to plan a break. The manager who
clicked gets a brief confirmation.

The message is bot-voiced (it does not impersonate the manager) and reads as care,
not surveillance. A nudge never books or modifies leave on anyone's behalf. The DM
is sent post-ack (like other slow handler work), so the click acks immediately.

## Acceptance criteria

- [ ] Each board row has a Nudge button that targets that specific person.
- [ ] Clicking Nudge makes the bot DM the correct at-risk person, in a supportive tone, citing the reason (no-break stretch and/or expiring days) and suggesting `/advance`.
- [ ] The DM is sent by the bot, not attributed to the manager, and reads as supportive rather than punitive.
- [ ] No leave request is created or modified by a nudge.
- [ ] The manager who clicked gets a brief confirmation.
- [ ] The nudge action is tested at the handler seam with the existing Slack fakes: correct recipient, supportive content naming the reason, and no request created.

## Blocked by

- 1: /burnout board tracer — #45
- 2: expiring-quota flag on /burnout — #46
