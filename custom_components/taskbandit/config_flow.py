"""Config and options flows for TaskBandit."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_SCAN_INTERVAL, CONF_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    TaskBanditAuthError,
    TaskBanditClient,
    TaskBanditConnectionError,
    TaskBanditError,
    TaskBanditFeatureDisabledError,
    TaskBanditScopeError,
    normalize_url,
)
from .const import (
    CONF_PRESENCE_MAP,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .models import TaskBanditState, parse_state

NO_MEMBER = "__none__"

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
        vol.Required(CONF_TOKEN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)
REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TOKEN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    }
)


async def _async_fetch_state(hass: HomeAssistant, url: str, token: str) -> TaskBanditState:
    client = TaskBanditClient(async_get_clientsession(hass), url, token)
    return parse_state(await client.get_state())


async def _async_validate(
    hass: HomeAssistant, url: str, token: str
) -> tuple[TaskBanditState | None, dict[str, str]]:
    """Call `GET /state`; return the state or a form error."""
    try:
        state = await _async_fetch_state(hass, url, token)
    except TaskBanditAuthError:
        return None, {"base": "invalid_auth"}
    except TaskBanditFeatureDisabledError:
        return None, {"base": "feature_disabled"}
    except TaskBanditScopeError:
        return None, {"base": "missing_scope"}
    except TaskBanditConnectionError:
        return None, {"base": "cannot_connect"}
    except (TaskBanditError, ValueError) as err:
        LOGGER.debug("Unexpected TaskBandit response: %s", err)
        return None, {"base": "unknown"}
    return state, {}


class TaskBanditConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up TaskBandit with a server address and token."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the server and token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            url = normalize_url(user_input[CONF_URL])
            token = user_input[CONF_TOKEN].strip()
            state, errors = await _async_validate(self.hass, url, token)
            if state is not None:
                await self.async_set_unique_id(state.household_id)
                self._abort_if_unique_id_configured(updates={CONF_URL: url, CONF_TOKEN: token})
                return self.async_create_entry(
                    title=state.household_name, data={CONF_URL: url, CONF_TOKEN: token}
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new token."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            state, errors = await _async_validate(self.hass, entry.data[CONF_URL], token)
            if state is not None:
                await self.async_set_unique_id(state.household_id)
                self._abort_if_unique_id_mismatch(reason="wrong_household")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_TOKEN: token}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"url": entry.data[CONF_URL]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return TaskBanditOptionsFlow()


class TaskBanditOptionsFlow(OptionsFlow):
    """Poll interval and presence mapping."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options."""
        entry = self.config_entry
        current_map: dict[str, str] = dict(entry.options.get(CONF_PRESENCE_MAP) or {})

        state: TaskBanditState | None = None
        runtime = getattr(entry, "runtime_data", None)
        if runtime is not None and runtime.coordinator.data is not None:
            state = runtime.coordinator.data
        else:
            try:
                state = await _async_fetch_state(
                    self.hass, entry.data[CONF_URL], entry.data[CONF_TOKEN]
                )
            except (TaskBanditError, ValueError):
                state = None
        presence = state is not None and state.presence_enabled

        if user_input is not None:
            scan_interval = int(user_input.pop(CONF_SCAN_INTERVAL))
            if presence:
                presence_map = {
                    person: member
                    for person, member in user_input.items()
                    if member and member != NO_MEMBER
                }
            else:
                presence_map = current_map
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: scan_interval, CONF_PRESENCE_MAP: presence_map}
            )

        fields: dict[Any, Any] = {
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=1,
                    unit_of_measurement="s",
                    mode=NumberSelectorMode.BOX,
                )
            )
        }
        if presence and state is not None:
            options = [SelectOptionDict(value=NO_MEMBER, label="—")] + [
                SelectOptionDict(value=member.id, label=member.display_name)
                for member in state.members.values()
            ]
            for person in sorted(self.hass.states.async_entity_ids("person")):
                fields[vol.Optional(person, default=current_map.get(person, NO_MEMBER))] = (
                    SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                    )
                )

        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields))
