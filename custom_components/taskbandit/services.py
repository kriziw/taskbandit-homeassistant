"""Services for TaskBandit."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .members import member_for_context
from .const import (
    ATTR_CHORE_ID,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_MEMBER_ID,
    ATTR_ROUTINE_ID,
    DOMAIN,
    SCOPE_CHORES,
    SERVICE_ASSIGN_CHORE,
    SERVICE_COMPLETE_CHORE,
    SERVICE_RUN_ROUTINE,
    SERVICE_START_CHORE,
)
from .coordinator import TaskBanditConfigEntry, async_call_api

_ENTRY = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}
CHORE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CHORE_ID): cv.string,
        vol.Optional(ATTR_MEMBER_ID): cv.string,
        **_ENTRY,
    }
)
ASSIGN_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CHORE_ID): cv.string,
        vol.Required(ATTR_MEMBER_ID): cv.string,
        **_ENTRY,
    }
)
ROUTINE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ROUTINE_ID): cv.string,
        vol.Optional(ATTR_MEMBER_ID): cv.string,
        **_ENTRY,
    }
)


def _get_entry(hass: HomeAssistant, call: ServiceCall) -> TaskBanditConfigEntry:
    """Find the config entry a service call is for."""
    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(f"No TaskBandit entry with id {entry_id}")
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(f"TaskBandit entry {entry.title} is not loaded")
        return entry
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if not entries:
        raise ServiceValidationError("No TaskBandit household is set up")
    if len(entries) > 1:
        raise ServiceValidationError(
            "Several TaskBandit households are set up; pass config_entry_id"
        )
    return entries[0]


def _doer(hass: HomeAssistant, entry: TaskBanditConfigEntry, call: ServiceCall) -> str | None:
    """Who did it: an explicit member_id, else the member of the HA user who called."""
    return call.data.get(ATTR_MEMBER_ID) or member_for_context(
        hass, dict(entry.options), call.context
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the TaskBandit services."""

    async def _complete(call: ServiceCall) -> ServiceResponse:
        entry = _get_entry(hass, call)
        outcome = await async_call_api(
            hass,
            entry,
            SCOPE_CHORES,
            entry.runtime_data.client.complete_chore(
                call.data[ATTR_CHORE_ID], _doer(hass, entry, call)
            ),
        )
        await entry.runtime_data.coordinator.async_request_refresh()
        return {"outcome": outcome}

    async def _start(call: ServiceCall) -> ServiceResponse:
        entry = _get_entry(hass, call)
        outcome = await async_call_api(
            hass,
            entry,
            SCOPE_CHORES,
            entry.runtime_data.client.start_chore(
                call.data[ATTR_CHORE_ID], _doer(hass, entry, call)
            ),
        )
        await entry.runtime_data.coordinator.async_request_refresh()
        return {"outcome": outcome}

    async def _assign(call: ServiceCall) -> ServiceResponse:
        entry = _get_entry(hass, call)
        outcome = await async_call_api(
            hass,
            entry,
            SCOPE_CHORES,
            entry.runtime_data.client.assign_chore(
                call.data[ATTR_CHORE_ID], call.data[ATTR_MEMBER_ID]
            ),
        )
        await entry.runtime_data.coordinator.async_request_refresh()
        return {"outcome": outcome}

    async def _run(call: ServiceCall) -> ServiceResponse:
        from .button import async_run_routine  # noqa: PLC0415

        entry = _get_entry(hass, call)
        return await async_run_routine(
            hass, entry, call.data[ATTR_ROUTINE_ID], _doer(hass, entry, call)
        )

    for name, handler, schema in (
        (SERVICE_COMPLETE_CHORE, _complete, CHORE_SCHEMA),
        (SERVICE_START_CHORE, _start, CHORE_SCHEMA),
        (SERVICE_ASSIGN_CHORE, _assign, ASSIGN_SCHEMA),
        (SERVICE_RUN_ROUTINE, _run, ROUTINE_SCHEMA),
    ):
        hass.services.async_register(
            DOMAIN, name, handler, schema=schema, supports_response=SupportsResponse.OPTIONAL
        )
