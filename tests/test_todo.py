"""To-do completion and service tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.taskbandit.const import DOMAIN, EVENT_ROUTINE_RUN

from .conftest import API, BEA, HOUSEHOLD_ID, calls_to, setup_entry


def _todo(hass: HomeAssistant, key: str) -> str:
    return er.async_get(hass).async_get_entity_id("todo", DOMAIN, f"{HOUSEHOLD_ID}_{key}")


@pytest.mark.parametrize(
    ("outcome", "text"),
    [
        ("completed", "is done"),
        ("submitted", "sent for approval"),
        ("proof_required", "needs a photo in the app"),
    ],
)
async def test_complete_todo_item(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    state_payload,
    outcome: str,
    text: str,
) -> None:
    """Ticking off an item completes the chore and reports the outcome."""
    await setup_entry(hass, config_entry, aioclient_mock, state_payload)
    aioclient_mock.post(f"{API}/chores/c-dish/complete", json={"outcome": outcome})
    polls = len(calls_to(aioclient_mock, "GET", "/state"))

    with patch(
        "custom_components.taskbandit.todo.persistent_notification.async_create"
    ) as notify:
        await hass.services.async_call(
            "todo",
            "update_item",
            {"item": "c-dish", "status": "completed"},
            target={"entity_id": _todo(hass, f"{BEA}_chores")},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert len(calls_to(aioclient_mock, "POST", "/chores/c-dish/complete")) == 1
    notify.assert_called_once()
    assert text in notify.call_args.args[1]
    assert "Empty the dishwasher" in notify.call_args.args[1]
    assert len(calls_to(aioclient_mock, "GET", "/state")) > polls


async def test_complete_missing_scope(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    state_payload,
) -> None:
    """A token without the chores scope gives a clear error and a repair issue."""
    await setup_entry(hass, config_entry, aioclient_mock, state_payload)
    aioclient_mock.post(
        f"{API}/chores/c-plants/complete", status=403, json={"code": "token_scope"}
    )
    with pytest.raises(HomeAssistantError, match="'chores' scope"):
        await hass.services.async_call(
            "todo",
            "update_item",
            {"item": "Water the plants", "status": "completed"},
            target={"entity_id": _todo(hass, "unassigned_chores")},
            blocking=True,
        )
    assert ir.async_get(hass).async_get_issue(DOMAIN, "missing_scope_chores")


async def test_services(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    state_payload,
) -> None:
    """The services call the matching endpoints."""
    await setup_entry(hass, config_entry, aioclient_mock, state_payload)
    aioclient_mock.post(f"{API}/chores/c-dish/start", json={"outcome": "started"})
    aioclient_mock.post(f"{API}/chores/c-dish/assign", json={"outcome": "assigned"})
    aioclient_mock.post(f"{API}/chores/c-dish/complete", json={"outcome": "submitted"})
    aioclient_mock.post(
        f"{API}/routines/r-bed/run", json={"status": "completed", "actions": []}
    )
    runs = async_capture_events(hass, EVENT_ROUTINE_RUN)

    result = await hass.services.async_call(
        DOMAIN, "start_chore", {"chore_id": "c-dish"}, blocking=True, return_response=True
    )
    assert result == {"outcome": "started"}
    await hass.services.async_call(
        DOMAIN,
        "assign_chore",
        {"chore_id": "c-dish", "member_id": BEA, "config_entry_id": config_entry.entry_id},
        blocking=True,
    )
    assign = calls_to(aioclient_mock, "POST", "/chores/c-dish/assign")
    assert assign[0][2] == {"memberId": BEA}
    result = await hass.services.async_call(
        DOMAIN, "complete_chore", {"chore_id": "c-dish"}, blocking=True, return_response=True
    )
    assert result == {"outcome": "submitted"}
    await hass.services.async_call(
        DOMAIN, "run_routine", {"routine_id": "r-bed"}, blocking=True
    )
    assert len(runs) == 1
    assert runs[0].data["routine_name"] == "Bedtime hand-off"
    assert runs[0].data["status"] == "completed"


async def test_routine_button(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    state_payload,
) -> None:
    """Pressing a routine button runs it and fires the result."""
    await setup_entry(hass, config_entry, aioclient_mock, state_payload)
    aioclient_mock.post(
        f"{API}/routines/r-bed/run", json={"status": "skipped", "actions": []}
    )
    runs = async_capture_events(hass, EVENT_ROUTINE_RUN)
    entity_id = er.async_get(hass).async_get_entity_id(
        "button", DOMAIN, f"{HOUSEHOLD_ID}_routine_r-bed_run"
    )
    await hass.services.async_call(
        "button", "press", target={"entity_id": entity_id}, blocking=True
    )
    assert len(calls_to(aioclient_mock, "POST", "/routines/r-bed/run")) == 1
    assert runs[0].data["status"] == "skipped"
