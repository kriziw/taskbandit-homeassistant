"""Sensors for TaskBandit."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import TaskBanditConfigEntry, TaskBanditCoordinator
from .entity import TaskBanditEntity, TaskBanditMemberEntity, async_add_dynamic_entities
from .models import Member, TaskBanditState

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MemberSensorDescription(SensorEntityDescription):
    """A per-member sensor."""

    value_fn: Callable[[Member], int]


@dataclass(frozen=True, kw_only=True)
class HouseholdSensorDescription(SensorEntityDescription):
    """A household sensor."""

    value_fn: Callable[[TaskBanditState], float | int | None]
    attrs_fn: Callable[[TaskBanditState], dict[str, Any] | None] = lambda _: None


MEMBER_SENSORS: tuple[MemberSensorDescription, ...] = (
    MemberSensorDescription(
        key="points",
        translation_key="points",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda member: member.points,
    ),
    MemberSensorDescription(
        key="streak",
        translation_key="streak",
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda member: member.streak,
    ),
    MemberSensorDescription(
        key="open_chores",
        translation_key="open_chores",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda member: member.open_chores,
    ),
    MemberSensorDescription(
        key="overdue_chores",
        translation_key="overdue_chores",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda member: member.overdue_chores,
    ),
)


def _goal_progress(state: TaskBanditState) -> float | None:
    if state.goal is None:
        return None
    return round(state.goal.progress * 100, 1)


def _goal_attrs(state: TaskBanditState) -> dict[str, Any] | None:
    if state.goal is None:
        return None
    return {
        "title": state.goal.title,
        "points": state.goal.points,
        "target_points": state.goal.target_points,
    }


HOUSEHOLD_SENSORS: tuple[HouseholdSensorDescription, ...] = (
    HouseholdSensorDescription(
        key="due_today",
        translation_key="due_today",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: state.due_today_count,
    ),
    HouseholdSensorDescription(
        key="overdue",
        translation_key="overdue",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: state.overdue_count,
    ),
    HouseholdSensorDescription(
        key="goal_progress",
        translation_key="goal_progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_goal_progress,
        attrs_fn=_goal_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskBanditConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TaskBandit sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        TaskBanditHouseholdSensor(coordinator, description)
        for description in HOUSEHOLD_SENSORS
    )
    async_add_dynamic_entities(
        entry,
        async_add_entities,
        lambda state: state.members,
        lambda member_id: [
            TaskBanditMemberSensor(coordinator, member_id, description)
            for description in MEMBER_SENSORS
        ],
    )


class TaskBanditMemberSensor(TaskBanditMemberEntity, SensorEntity):
    """A sensor for one member."""

    entity_description: MemberSensorDescription

    def __init__(
        self,
        coordinator: TaskBanditCoordinator,
        member_id: str,
        description: MemberSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, member_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | None:
        """Return the value."""
        member = self.member
        return None if member is None else self.entity_description.value_fn(member)


class TaskBanditHouseholdSensor(TaskBanditEntity, SensorEntity):
    """A sensor for the household."""

    entity_description: HouseholdSensorDescription

    def __init__(
        self, coordinator: TaskBanditCoordinator, description: HouseholdSensorDescription
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | None:
        """Return the value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        return self.entity_description.attrs_fn(self.coordinator.data)
