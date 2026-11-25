"""Binary sensor for TaskBandit."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import TaskBanditConfigEntry, TaskBanditCoordinator
from .entity import TaskBanditEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskBanditConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor."""
    async_add_entities([ChoresOverdueBinarySensor(entry.runtime_data.coordinator)])


class ChoresOverdueBinarySensor(TaskBanditEntity, BinarySensorEntity):
    """On while any chore is overdue."""

    _attr_translation_key = "chores_overdue"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: TaskBanditCoordinator) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, "chores_overdue")

    @property
    def is_on(self) -> bool:
        """Return true if any chore is overdue."""
        return self.coordinator.data.overdue_count > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """List the overdue chores."""
        return {
            "chores": [chore.title for chore in self.coordinator.data.chores if chore.overdue]
        }
