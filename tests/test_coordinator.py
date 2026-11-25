"""Snapshot parsing and entity tests."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.taskbandit.const import DOMAIN
from custom_components.taskbandit.models import parse_state

from .conftest import API, BEA, HOUSEHOLD_ID, TOM, setup_entry


def test_parse_state(state_payload) -> None:
    """The snapshot is parsed into members, chores, goal and routines."""
    state = parse_state(state_payload)
    assert state.household_id == HOUSEHOLD_ID
    assert state.household_name == "Home"
    assert state.server_version == "1.26.0"
    assert state.presence_enabled is True
    assert state.members[BEA].points == 340
    assert state.members[BEA].streak == 5
    assert state.members[TOM].presence is None
    assert [c.id for c in state.chores_for(BEA)] == ["c-dish", "c-bins"]
    assert [c.id for c in state.chores_for(None)] == ["c-plants"]
    assert state.overdue_count == 1
    assert state.due_today_count == 2
    assert state.chores[0].due_at is not None
    assert state.chores[2].due_at is None
    assert state.goal is not None
    assert state.goal.progress == 0.82
    assert state.routines["r-bed"].name == "Bedtime hand-off"


def test_parse_state_without_goal(state_payload) -> None:
    """A null goal is fine."""
    state_payload["goal"] = None
    assert parse_state(state_payload).goal is None


def _entity(hass: HomeAssistant, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{HOUSEHOLD_ID}_{key}"
    )
    assert entity_id, key
    return entity_id


async def test_entities(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    state_payload,
) -> None:
    """Sensors, binary sensor, button and to-do lists reflect the snapshot."""
    await setup_entry(hass, config_entry, aioclient_mock, state_payload)
    assert config_entry.state is ConfigEntryState.LOADED

    assert hass.states.get(_entity(hass, "sensor", f"{BEA}_points")).state == "340"
    assert hass.states.get(_entity(hass, "sensor", f"{BEA}_streak")).state == "5"
    assert hass.states.get(_entity(hass, "sensor", f"{BEA}_open_chores")).state == "3"
    assert hass.states.get(_entity(hass, "sensor", f"{BEA}_overdue_chores")).state == "1"
    assert hass.states.get(_entity(hass, "sensor", "due_today")).state == "2"
    assert hass.states.get(_entity(hass, "sensor", "overdue")).state == "1"
    goal = hass.states.get(_entity(hass, "sensor", "goal_progress"))
    assert goal.state == "82.0"
    assert goal.attributes["title"] == "Zoo trip"
    assert goal.attributes["target_points"] == 1000
    assert hass.states.get(_entity(hass, "binary_sensor", "chores_overdue")).state == "on"
    assert hass.states.get(_entity(hass, "button", "routine_r-bed_run")) is not None
    assert hass.states.get(_entity(hass, "todo", f"{BEA}_chores")).state == "2"
    assert hass.states.get(_entity(hass, "todo", f"{TOM}_chores")).state == "0"
    assert hass.states.get(_entity(hass, "todo", "unassigned_chores")).state == "1"


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A 401 while polling starts reauth."""
    aioclient_mock.get(f"{API}/state", status=401)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_missing_scope_raises_issue(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A 403 token_scope creates a repair issue naming the scope."""
    aioclient_mock.get(f"{API}/state", status=403, json={"code": "token_scope"})
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "missing_scope_read")
    assert issue is not None
    assert issue.translation_placeholders["scope"] == "read"
