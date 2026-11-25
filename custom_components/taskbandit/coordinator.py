"""Data coordinator and runtime data for TaskBandit."""

from __future__ import annotations

from collections import deque
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    TaskBanditAuthError,
    TaskBanditClient,
    TaskBanditError,
    TaskBanditFeatureDisabledError,
    TaskBanditScopeError,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER, SCOPE_READ
from .models import TaskBanditState, parse_state

_T = TypeVar("_T")


@dataclass
class TaskBanditRuntimeData:
    """Objects that live as long as the config entry is loaded."""

    client: TaskBanditClient
    coordinator: TaskBanditCoordinator
    options: dict[str, Any]
    webhook_id: str | None = None
    seen_deliveries: deque[str] = field(default_factory=lambda: deque(maxlen=200))
    presence_disabled_logged: bool = False


type TaskBanditConfigEntry = ConfigEntry[TaskBanditRuntimeData]


def _issue_id(scope: str) -> str:
    return f"missing_scope_{scope}"


@callback
def async_report_missing_scope(
    hass: HomeAssistant, entry: ConfigEntry, scope: str
) -> None:
    """Log and raise a repair issue naming the scope the token lacks."""
    LOGGER.error(
        "The TaskBandit token for %s is missing the '%s' scope. Create a token "
        "with that scope in TaskBandit (Settings > Integrations > Home Assistant) "
        "and reauthenticate the integration",
        entry.title,
        scope,
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id(scope),
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="missing_scope",
        translation_placeholders={"scope": scope, "household": entry.title},
    )


@callback
def async_clear_missing_scope(hass: HomeAssistant, scope: str) -> None:
    """Remove the repair issue for a scope once a call with it succeeds."""
    ir.async_delete_issue(hass, DOMAIN, _issue_id(scope))


async def async_call_api(
    hass: HomeAssistant, entry: ConfigEntry, scope: str, call: Awaitable[_T]
) -> _T:
    """Run an API call from an action and turn errors into HA errors."""
    try:
        result = await call
    except TaskBanditAuthError as err:
        entry.async_start_reauth(hass)
        raise HomeAssistantError(
            "TaskBandit rejected the token. Reauthenticate the integration."
        ) from err
    except TaskBanditScopeError as err:
        async_report_missing_scope(hass, entry, err.scope)
        raise HomeAssistantError(
            f"The TaskBandit token is missing the '{err.scope}' scope"
        ) from err
    except TaskBanditFeatureDisabledError as err:
        raise HomeAssistantError(
            f"This feature is turned off for the TaskBandit household: {err}"
        ) from err
    except TaskBanditError as err:
        raise HomeAssistantError(f"TaskBandit request failed: {err}") from err
    async_clear_missing_scope(hass, scope)
    return result


class TaskBanditCoordinator(DataUpdateCoordinator[TaskBanditState]):
    """Polls `GET /state`."""

    config_entry: TaskBanditConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: TaskBanditClient
    ) -> None:
        """Set up the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            ),
        )
        self.client = client

    async def _async_update_data(self) -> TaskBanditState:
        try:
            data = await self.client.get_state()
        except TaskBanditAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TaskBanditScopeError as err:
            async_report_missing_scope(self.hass, self.config_entry, err.scope)
            raise UpdateFailed(
                f"The TaskBandit token is missing the '{err.scope}' scope"
            ) from err
        except TaskBanditFeatureDisabledError as err:
            raise UpdateFailed(
                f"The home_assistant feature is turned off in TaskBandit: {err}"
            ) from err
        except TaskBanditError as err:
            raise UpdateFailed(str(err)) from err
        try:
            state = parse_state(data)
        except ValueError as err:
            raise UpdateFailed(str(err)) from err
        async_clear_missing_scope(self.hass, SCOPE_READ)
        return state
