"""Routine buttons for TaskBandit."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .members import member_for_context
from .const import EVENT_ROUTINE_RUN, SCOPE_ROUTINES
from .coordinator import TaskBanditConfigEntry, TaskBanditCoordinator, async_call_api
from .entity import TaskBanditRoutineEntity, async_add_dynamic_entities

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskBanditConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a button per routine."""
    coordinator = entry.runtime_data.coordinator
    async_add_dynamic_entities(
        entry,
        async_add_entities,
        lambda state: state.routines,
        lambda routine_id: [RunRoutineButton(coordinator, routine_id)],
    )


async def async_run_routine(
    hass: HomeAssistant,
    entry: TaskBanditConfigEntry,
    routine_id: str,
    member_id: str | None = None,
) -> dict:
    """Run a routine (for `member_id`, if known), fire `taskbandit_routine_run` and refresh."""
    runtime = entry.runtime_data
    run = await async_call_api(
        hass, entry, SCOPE_ROUTINES, runtime.client.run_routine(routine_id, member_id)
    )
    routine = runtime.coordinator.data.routines.get(routine_id)
    hass.bus.async_fire(
        EVENT_ROUTINE_RUN,
        {
            "config_entry_id": entry.entry_id,
            "routine_id": routine_id,
            "routine_name": routine.name if routine else None,
            "member_id": member_id,
            "status": run.get("status"),
            "run": run,
        },
    )
    await runtime.coordinator.async_request_refresh()
    return run


class RunRoutineButton(TaskBanditRoutineEntity, ButtonEntity):
    """Runs a routine."""

    _attr_translation_key = "run_routine"

    def __init__(self, coordinator: TaskBanditCoordinator, routine_id: str) -> None:
        """Initialise the button."""
        super().__init__(coordinator, routine_id, "run")

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the routine id and whether it is enabled."""
        routine = self.routine
        return {
            "routine_id": self.routine_id,
            "enabled": routine.enabled if routine else None,
        }

    async def async_press(self) -> None:
        """Run the routine."""
        entry = self.coordinator.config_entry
        await async_run_routine(
            self.hass,
            entry,
            self.routine_id,
            member_for_context(self.hass, dict(entry.options), self._context),
        )
