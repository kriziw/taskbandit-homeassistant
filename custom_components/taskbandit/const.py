"""Constants for the TaskBandit integration."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "taskbandit"
LOGGER = logging.getLogger(__package__)

API_PATH: Final = "/api/integrations/home-assistant"
# TaskBandit Cloud: the household is found from the token, so this is all a hosted user needs.
CLOUD_URL: Final = "https://api.taskbandit.app"
# True for TaskBandit Cloud, False for a self-hosted server.
CONF_HOSTED: Final = "hosted"
REQUEST_TIMEOUT: Final = 15

CONF_WEBHOOK_SECRET: Final = "webhook_secret"
CONF_CLOUDHOOK: Final = "cloudhook"
CONF_PRESENCE_MAP: Final = "presence_map"

DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 15
MAX_SCAN_INTERVAL: Final = 3600

# Signature checking for pushed webhook events (see TaskBandit docs/webhooks.md).
HEADER_SIGNATURE: Final = "X-TaskBandit-Signature"
HEADER_TIMESTAMP: Final = "X-TaskBandit-Timestamp"
HEADER_DELIVERY: Final = "X-TaskBandit-Delivery"
SIGNATURE_MAX_AGE: Final = 300

# Events fired on the Home Assistant bus.
EVENT_TASKBANDIT: Final = "taskbandit_event"
EVENT_ROUTINE_STEP: Final = "taskbandit_routine_step"
EVENT_ROUTINE_RUN: Final = "taskbandit_routine_run"
HA_EVENT_TYPE: Final = "home_assistant.event"

# Token scopes.
SCOPE_READ: Final = "read"
SCOPE_CHORES: Final = "chores"
SCOPE_ROUTINES: Final = "routines"
SCOPE_PRESENCE: Final = "presence"

# Service names and fields.
SERVICE_COMPLETE_CHORE: Final = "complete_chore"
SERVICE_START_CHORE: Final = "start_chore"
SERVICE_ASSIGN_CHORE: Final = "assign_chore"
SERVICE_RUN_ROUTINE: Final = "run_routine"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_CHORE_ID: Final = "chore_id"
ATTR_MEMBER_ID: Final = "member_id"
ATTR_ROUTINE_ID: Final = "routine_id"

# Messages for the persistent notification that reports a completion outcome.
OUTCOME_MESSAGES: Final[dict[str, dict[str, str]]] = {
    "en": {
        "title": "TaskBandit",
        "completed": "“{title}” is done.",
        "submitted": "“{title}” was sent for approval.",
        "proof_required": "“{title}” needs a photo in the app.",
        "already_done": "“{title}” was already done.",
        "unknown": "“{title}”: {outcome}.",
    },
    "de": {
        "title": "TaskBandit",
        "completed": "„{title}“ ist erledigt.",
        "submitted": "„{title}“ wurde zur Freigabe gesendet.",
        "proof_required": "„{title}“ braucht ein Foto in der App.",
        "already_done": "„{title}“ war schon erledigt.",
        "unknown": "„{title}“: {outcome}.",
    },
    "hu": {
        "title": "TaskBandit",
        "completed": "„{title}” kész.",
        "submitted": "„{title}” jóváhagyásra elküldve.",
        "proof_required": "„{title}” fotót igényel az alkalmazásban.",
        "already_done": "„{title}” már kész volt.",
        "unknown": "„{title}”: {outcome}.",
    },
}
