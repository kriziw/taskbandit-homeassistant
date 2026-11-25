"""Base entities for TaskBandit."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TaskBanditConfigEntry, TaskBanditCoordinator
from .models import Member, Routine, TaskBanditState


class TaskBanditEntity(CoordinatorEntity[TaskBanditCoordinator]):
    """An entity on the household device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TaskBanditCoordinator, key: str) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        data = coordinator.data
        self._attr_unique_id = f"{data.household_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, data.household_id)},
            name=data.household_name,
            manufacturer="TaskBandit",
            model="Household",
            sw_version=data.server_version,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=coordinator.client.server_url,
        )


class TaskBanditMemberEntity(TaskBanditEntity):
    """An entity for one household member."""

    def __init__(
        self, coordinator: TaskBanditCoordinator, member_id: str, key: str
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator, f"{member_id}_{key}")
        self.member_id = member_id
        self._attr_translation_placeholders = {
            "member": coordinator.data.members[member_id].display_name
        }

    @property
    def member(self) -> Member | None:
        """The member, or None once they're gone."""
        return self.coordinator.data.members.get(self.member_id)

    @property
    def available(self) -> bool:
        """Unavailable once the member leaves the household."""
        return super().available and self.member is not None


class TaskBanditRoutineEntity(TaskBanditEntity):
    """An entity for one routine."""

    def __init__(
        self, coordinator: TaskBanditCoordinator, routine_id: str, key: str
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator, f"routine_{routine_id}_{key}")
        self.routine_id = routine_id
        self._attr_translation_placeholders = {
            "routine": coordinator.data.routines[routine_id].name
        }

    @property
    def routine(self) -> Routine | None:
        """The routine, or None once it's deleted."""
        return self.coordinator.data.routines.get(self.routine_id)

    @property
    def available(self) -> bool:
        """Unavailable once the routine is deleted."""
        return super().available and self.routine is not None


@callback
def async_add_dynamic_entities(
    entry: TaskBanditConfigEntry,
    async_add_entities: AddEntitiesCallback,
    ids: Callable[[TaskBanditState], Iterable[str]],
    factory: Callable[[str], list[Entity]],
) -> None:
    """Add entities for each id now and for ids that appear later."""
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    @callback
    def _async_check() -> None:
        new = [item for item in ids(coordinator.data) if item not in known]
        if not new:
            return
        known.update(new)
        async_add_entities([entity for item in new for entity in factory(item)])

    _async_check()
    entry.async_on_unload(coordinator.async_add_listener(_async_check))
