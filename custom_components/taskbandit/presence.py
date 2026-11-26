"""Report HA person presence to TaskBandit."""

from __future__ import annotations

from typing import Any

from homeassistant.const import STATE_HOME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.start import async_at_started

from .api import TaskBanditError, TaskBanditPresenceDisabledError, TaskBanditScopeError
from .const import LOGGER, SCOPE_PRESENCE
from .members import person_to_member
from .coordinator import (
    TaskBanditConfigEntry,
    async_clear_missing_scope,
    async_report_missing_scope,
)


def _is_home(state: State | None) -> bool | None:
    """True for `home`, False for any other known state, None if unknown."""
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    return state.state == STATE_HOME


@callback
def async_setup_presence(hass: HomeAssistant, entry: TaskBanditConfigEntry) -> None:
    """Track mapped persons and send `PUT /presence` when they come or go."""
    mapping: dict[str, str] = person_to_member(dict(entry.options))
    if not mapping:
        return
    runtime = entry.runtime_data

    async def _async_send(members: list[dict[str, Any]]) -> None:
        try:
            await runtime.client.set_presence(members)
        except TaskBanditPresenceDisabledError:
            if not runtime.presence_disabled_logged:
                LOGGER.info(
                    "Presence is turned off for this TaskBandit household; "
                    "turn it on in TaskBandit to report who is home"
                )
                runtime.presence_disabled_logged = True
            return
        except TaskBanditScopeError as err:
            async_report_missing_scope(hass, entry, err.scope)
            return
        except TaskBanditError as err:
            LOGGER.warning("Could not report presence to TaskBandit: %s", err)
            return
        runtime.presence_disabled_logged = False
        async_clear_missing_scope(hass, SCOPE_PRESENCE)

    @callback
    def _async_state_changed(event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        member_id = mapping.get(entity_id)
        new = _is_home(event.data["new_state"])
        if member_id is None or new is None or new == _is_home(event.data["old_state"]):
            return
        entry.async_create_background_task(
            hass,
            _async_send([{"memberId": member_id, "home": new}]),
            "taskbandit_presence",
        )

    entry.async_on_unload(
        async_track_state_change_event(hass, list(mapping), _async_state_changed)
    )

    async def _async_send_all(_hass: HomeAssistant) -> None:
        members = []
        for entity_id, member_id in mapping.items():
            home = _is_home(hass.states.get(entity_id))
            if home is not None:
                members.append({"memberId": member_id, "home": home})
        if members:
            await _async_send(members)

    entry.async_on_unload(async_at_started(hass, _async_send_all))
