# TaskBandit for Home Assistant

[![Validate](https://github.com/kriziw/taskbandit-homeassistant/actions/workflows/validate.yml/badge.svg)](https://github.com/kriziw/taskbandit-homeassistant/actions/workflows/validate.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)

A Home Assistant integration for [TaskBandit](https://github.com/kriziw/taskbandit-ce), the family chore app. It shows each member's chores, points and streaks in Home Assistant, lets you tick chores off and run routines, and tells TaskBandit who is home.

> Screenshot: device page *(placeholder)*
>
> Screenshot: a member's to-do list *(placeholder)*

## What you get

- **A to-do list per member** with today's open chores, plus one list of **unassigned chores**. Ticking one off completes the chore in TaskBandit, following the household's approval and photo rules. A notification tells you what happened: done, sent for approval, or needs a photo in the app.
- **Sensors:**
  - **Per member:** points, day streak, open chores and overdue chores.
  - **For the household:** chores due today, overdue chores, and family goal progress (%, with the goal's title, points and target as attributes).
  - **Binary sensor:** "Chores overdue".
- **A button per routine** that runs it.
- **Events:**
  - `taskbandit_event` for every TaskBandit webhook event (`type`, `data`, `id`, `occurred_at`).
  - `taskbandit_routine_step` when a routine's **Tell Home Assistant** step runs (`label`, `routine`, `runner`).
  - `taskbandit_routine_run` after a routine is run from Home Assistant (`routine_id`, `routine_name`, `status`, `run`).
- **Services:** `taskbandit.complete_chore`, `taskbandit.start_chore`, `taskbandit.assign_chore` and `taskbandit.run_routine`. Each takes an optional `config_entry_id` if you have more than one household.
- **Presence (opt-in):** map Home Assistant people to TaskBandit members, and the integration reports when they arrive or leave, so routines can react.

The integration polls TaskBandit every 60 seconds (you can change this). If Home Assistant has an external address (for example through Home Assistant Cloud), it also registers a webhook with TaskBandit, so changes show up within a second. Each push is checked against its HMAC signature and rejected if it's older than 5 minutes.

## Requirements

- TaskBandit with the `home_assistant` feature: the Premium plan on TaskBandit Cloud, or a self-hosted server with a TaskBandit Premium licence.
- Home Assistant 2025.1 or later.
- For instant updates: a public HTTPS address for Home Assistant (for example Home Assistant Cloud) with hosted TaskBandit. Self-hosted TaskBandit can use any address it can reach. Push also needs the `webhooks` feature.

## Installation

### HACS (recommended)

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/kriziw/taskbandit-homeassistant` with the category **Integration**.
3. Search for **TaskBandit**, install it and restart Home Assistant.

### Manual

1. Download `taskbandit.zip` from the [latest release](https://github.com/kriziw/taskbandit-homeassistant/releases).
2. Unzip it into `config/custom_components/taskbandit/`.
3. Restart Home Assistant.

## Setup

1. In the TaskBandit web app, an admin opens **Settings → Integrations → Home Assistant** and creates a token. Choose what it may do:
   - `read` (always included)
   - `chores` to complete, start and assign chores
   - `routines` to run routines
   - `presence` to report who is home
   
   Also choose which member it acts as. The token (`tbha_…`) is shown only once.
2. In Home Assistant, go to **Settings → Devices & services → Add integration → TaskBandit**, then pick where your TaskBandit runs:
   - **TaskBandit Cloud:** paste the token. That's all; your household is found from the token.
   - **Self-hosted server:** enter your server's address, for example `http://192.168.1.10:8080`, and the token. Turn off **Check the certificate** only if your server uses a self-signed certificate.

   A self-hosted server on your network usually shows up by itself as **Discovered: TaskBandit**, with the address already filled in, so you only paste the token. The server announces itself over mDNS (`_taskbandit._tcp`). In Docker that needs host networking or an Avahi service file on the host.
3. **Who is who:** for each TaskBandit member, pick their Home Assistant person, or **Not in Home Assistant** for members who don't use it (a child without an HA account, say). It works like matching a robot vacuum's rooms to areas. Matching names are suggested. Home Assistant people nobody is matched to (guests, say) simply aren't TaskBandit members.
   - This decides who gets the credit. A routine button pressed, or a chore ticked off, by an HA user is sent as their member: "Run by Bea · from Home Assistant", points for whoever did an unassigned chore. Automations run without a member, like a scheduled routine.
   - It also decides who is reported home, if you turn on **Presence** in TaskBandit.
   - Change it any time under **Configure**. When it gets out of sync (a member or person added or removed), Home Assistant raises a repair, **Check who is who in TaskBandit**, which opens the same form.

**Instant updates:** besides polling, the integration registers a webhook so TaskBandit can push changes.
- **TaskBandit Cloud** needs Home Assistant reachable over public HTTPS, for example through Home Assistant Cloud.
- **A self-hosted server** can use Home Assistant's local address.
- **Otherwise** it simply polls.

> Screenshot: the setup dialog *(placeholder)*

### Options

- **Poll interval:** how often to fetch the status, in seconds (default 60).
- **Presence mapping:** shown only while presence is on in TaskBandit. A person whose state is `home` is reported as home; any other zone or `not_home` counts as away. `unknown` and `unavailable` aren't reported.

## Troubleshooting

- **"TaskBandit rejected the token":** the token was revoked, or its member is no longer an admin or parent. Home Assistant asks you to reauthenticate; create a new token and enter it.
- **"The Home Assistant feature is turned off":** the household's plan doesn't include `home_assistant`.
- **A repair says the token is missing a scope:** create a token with that scope and reauthenticate.
- **Changes only show up after a minute:** Home Assistant has no external address, or TaskBandit couldn't register the webhook. Check the log for `taskbandit`.

## Example automation

```yaml
alias: Kitchen light from a TaskBandit routine
triggers:
  - trigger: event
    event_type: taskbandit_routine_step
    event_data:
      label: kitchen_light
actions:
  - action: light.turn_on
    target:
      entity_id: light.kitchen
```

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

CI runs hassfest, the HACS validation and the tests on Python 3.13. Pushing a `v*` tag publishes a release with `taskbandit.zip`.

## License

MIT
