"""To-do lists for TaskBandit chores."""

from __future__ import annotations

from homeassistant.components import persistent_notification
from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import OUTCOME_MESSAGES, SCOPE_CHORES
from .coordinator import TaskBanditConfigEntry, TaskBanditCoordinator, async_call_api
from .entity import TaskBanditEntity, TaskBanditMemberEntity, async_add_dynamic_entities
from .members import member_for_context
from .models import Chore

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskBanditConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a to-do list per member plus one for unassigned chores."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities([HouseholdTodoList(coordinator)])
    async_add_dynamic_entities(
        entry,
        async_add_entities,
        lambda state: state.members,
        lambda member_id: [MemberTodoList(coordinator, member_id)],
    )


def _todo_item(chore: Chore) -> TodoItem:
    details = [part for part in (chore.group, f"{chore.points} points") if part]
    if chore.requires_photo:
        details.append("photo required")
    return TodoItem(
        uid=chore.id,
        summary=chore.title,
        status=TodoItemStatus.NEEDS_ACTION,
        due=dt_util.as_local(chore.due_at) if chore.due_at else None,
        description=" · ".join(details),
    )


def outcome_message(hass: HomeAssistant, title: str, outcome: str) -> tuple[str, str]:
    """Return the notification title and message for a completion outcome."""
    language = (hass.config.language or "en").split("-")[0]
    messages = OUTCOME_MESSAGES.get(language, OUTCOME_MESSAGES["en"])
    template = messages.get(outcome, messages["unknown"])
    return messages["title"], template.format(title=title, outcome=outcome)


class _ChoreTodoList(TaskBanditEntity, TodoListEntity):
    """Shared to-do behaviour."""

    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM
    _member_id: str | None = None

    @property
    def todo_items(self) -> list[TodoItem]:
        """Today's open chores."""
        return [_todo_item(chore) for chore in self.coordinator.data.chores_for(self._member_id)]

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Complete a chore when its item is ticked off."""
        if item.uid is None:
            raise HomeAssistantError("Unknown chore")
        chore = self.coordinator.data.chore(item.uid)
        if item.status != TodoItemStatus.COMPLETED:
            if chore is not None and item.summary in (None, chore.title):
                return
            raise HomeAssistantError(
                "TaskBandit chores can only be ticked off from Home Assistant"
            )
        entry = self.coordinator.config_entry
        outcome = await async_call_api(
            self.hass,
            entry,
            SCOPE_CHORES,
            entry.runtime_data.client.complete_chore(
                item.uid, member_for_context(self.hass, dict(entry.options), self._context)
            ),
        )
        title, message = outcome_message(
            self.hass, chore.title if chore else (item.summary or item.uid), outcome
        )
        persistent_notification.async_create(
            self.hass, message, title=title, notification_id=f"taskbandit_{item.uid}"
        )
        await self.coordinator.async_request_refresh()


class MemberTodoList(TaskBanditMemberEntity, _ChoreTodoList):
    """Today's chores for one member."""

    _attr_translation_key = "member_chores"

    def __init__(self, coordinator: TaskBanditCoordinator, member_id: str) -> None:
        """Initialise the list."""
        super().__init__(coordinator, member_id, "chores")
        self._member_id = member_id


class HouseholdTodoList(_ChoreTodoList):
    """Today's unassigned chores."""

    _attr_translation_key = "unassigned_chores"

    def __init__(self, coordinator: TaskBanditCoordinator) -> None:
        """Initialise the list."""
        super().__init__(coordinator, "unassigned_chores")
