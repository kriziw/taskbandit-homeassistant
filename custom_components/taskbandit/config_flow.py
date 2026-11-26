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
from homeassistant.const import (
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_URL,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
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
    CLOUD_URL,
    CONF_HOSTED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .members import mapping_from_input, mapping_schema, persons
from .models import TaskBanditState, parse_state

TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

CLOUD_SCHEMA = vol.Schema({vol.Required(CONF_TOKEN): TOKEN_SELECTOR})
SELF_HOSTED_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
        vol.Required(CONF_TOKEN): TOKEN_SELECTOR,
        vol.Required(CONF_VERIFY_SSL, default=True): BooleanSelector(),
    }
)
REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TOKEN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    }
)


async def _async_fetch_state(
    hass: HomeAssistant, url: str, token: str, verify_ssl: bool = True
) -> TaskBanditState:
    client = TaskBanditClient(async_get_clientsession(hass, verify_ssl=verify_ssl), url, token)
    return parse_state(await client.get_state())


async def _async_validate(
    hass: HomeAssistant, url: str, token: str, verify_ssl: bool = True
) -> tuple[TaskBanditState | None, dict[str, str]]:
    """Call `GET /state`; return the state or a form error."""
    try:
        state = await _async_fetch_state(hass, url, token, verify_ssl)
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
    """Set up TaskBandit Cloud with just a token, or a self-hosted server.

    Self-hosted servers announce themselves on the network (`_taskbandit._tcp`);
    Home Assistant then offers them with the address filled in.
    """

    VERSION = 3

    def __init__(self) -> None:
        """Start a flow."""
        self._discovered_url: str | None = None
        self._pending: tuple[TaskBanditState, dict[str, Any]] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask where TaskBandit runs."""
        return self.async_show_menu(step_id="user", menu_options=["cloud", "self_hosted"])

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """TaskBandit Cloud: only the token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            state, errors = await _async_validate(self.hass, CLOUD_URL, token)
            if state is not None:
                return await self._async_create(state, CLOUD_URL, token, True, True)
        return self.async_show_form(step_id="cloud", data_schema=CLOUD_SCHEMA, errors=errors)

    async def async_step_self_hosted(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """A self-hosted server: its address (filled in when discovered) and the token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            url = normalize_url(user_input[CONF_URL], default_scheme="http")
            token = user_input[CONF_TOKEN].strip()
            verify_ssl = bool(user_input.get(CONF_VERIFY_SSL, True))
            state, errors = await _async_validate(self.hass, url, token, verify_ssl)
            if state is not None:
                return await self._async_create(state, url, token, False, verify_ssl)
        suggested = user_input or (
            {CONF_URL: self._discovered_url} if self._discovered_url else None
        )
        return self.async_show_form(
            step_id="self_hosted",
            data_schema=self.add_suggested_values_to_schema(SELF_HOSTED_SCHEMA, suggested),
            errors=errors,
        )

    async def async_step_zeroconf(self, discovery_info: Any) -> ConfigFlowResult:
        """A self-hosted TaskBandit server announced itself on the network."""
        properties = getattr(discovery_info, "properties", {}) or {}
        announced = str(properties.get("api") or "").strip()
        if announced:
            url = normalize_url(announced, default_scheme="http")
        else:
            host = str(discovery_info.host)
            if ":" in host:
                host = f"[{host}]"
            url = f"http://{host}:{discovery_info.port}"
        self._async_abort_entries_match({CONF_URL: url})
        await self.async_set_unique_id(f"discovered:{url}")
        self._abort_if_unique_id_configured()
        self._discovered_url = url
        self.context["title_placeholders"] = {"url": url}
        return await self.async_step_self_hosted()

    async def _async_create(
        self,
        state: TaskBanditState,
        url: str,
        token: str,
        hosted: bool,
        verify_ssl: bool,
    ) -> ConfigFlowResult:
        data = {
            CONF_URL: url,
            CONF_TOKEN: token,
            CONF_HOSTED: hosted,
            CONF_VERIFY_SSL: verify_ssl,
        }
        await self.async_set_unique_id(state.household_id, raise_on_progress=False)
        self._abort_if_unique_id_configured(updates=data)
        self._pending = (state, data)
        return await self.async_step_members()

    async def async_step_members(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Which Home Assistant person is which TaskBandit member."""
        assert self._pending is not None
        state, data = self._pending
        errors: dict[str, str] = {}
        if user_input is None and not persons(self.hass):
            # No people in Home Assistant: nobody to map, so nobody is asked.
            user_input = {}
        if user_input is not None:
            mapping, errors = mapping_from_input(self.hass, state, user_input)
            if not errors:
                return self.async_create_entry(
                    title=state.household_name, data=data, options=mapping
                )
        return self.async_show_form(
            step_id="members",
            data_schema=mapping_schema(self.hass, state, {}),
            errors=errors,
            description_placeholders={"household": state.household_name},
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
            state, errors = await _async_validate(
                self.hass, entry.data[CONF_URL], token, entry.data.get(CONF_VERIFY_SSL, True)
            )
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
    """Poll interval and the member ↔ person mapping."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options."""
        entry = self.config_entry
        state: TaskBanditState | None = None
        runtime = getattr(entry, "runtime_data", None)
        if runtime is not None and runtime.coordinator.data is not None:
            state = runtime.coordinator.data
        else:
            try:
                state = await _async_fetch_state(
                    self.hass,
                    entry.data[CONF_URL],
                    entry.data[CONF_TOKEN],
                    entry.data.get(CONF_VERIFY_SSL, True),
                )
            except (TaskBanditError, ValueError):
                state = None

        errors: dict[str, str] = {}
        if user_input is not None:
            scan_interval = int(user_input.pop(CONF_SCAN_INTERVAL))
            mapping: dict[str, Any] = {}
            if state is not None:
                mapping, errors = mapping_from_input(self.hass, state, user_input)
            if not errors:
                return self.async_create_entry(
                    data={**entry.options, **mapping, CONF_SCAN_INTERVAL: scan_interval}
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
        if state is not None:
            fields.update(mapping_schema(self.hass, state, dict(entry.options)).schema)
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(fields), errors=errors
        )
