"""Shared fixtures for TaskBandit tests."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from homeassistant.const import CONF_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.taskbandit.const import DOMAIN

SERVER = "https://tb.example.com"
API = f"{SERVER}/api/integrations/home-assistant"
TOKEN = "tbha_test_token"
HOUSEHOLD_ID = "hh-1"
BEA = "m-bea"
TOM = "m-tom"

STATE: dict[str, Any] = {
    "household": {"id": HOUSEHOLD_ID, "name": "Home", "timezone": "Europe/Budapest"},
    "serverVersion": "1.26.0",
    "presenceEnabled": True,
    "members": [
        {
            "id": BEA,
            "displayName": "Bea",
            "role": "child",
            "points": 340,
            "streak": 5,
            "openChores": 3,
            "overdueChores": 1,
            "dueToday": 2,
            "presence": "home",
        },
        {
            "id": TOM,
            "displayName": "Tom",
            "role": "parent",
            "points": 120,
            "streak": 0,
            "openChores": 0,
            "overdueChores": 0,
            "dueToday": 0,
            "presence": None,
        },
    ],
    "chores": [
        {
            "id": "c-dish",
            "title": "Empty the dishwasher",
            "group": "Kitchen",
            "assigneeId": BEA,
            "dueAt": "2026-11-25T17:00:00.000Z",
            "overdue": False,
            "state": "assigned",
            "requiresPhoto": False,
            "points": 10,
        },
        {
            "id": "c-bins",
            "title": "Take out the bins",
            "group": None,
            "assigneeId": BEA,
            "dueAt": "2026-11-25T07:00:00.000Z",
            "overdue": True,
            "state": "overdue",
            "requiresPhoto": True,
            "points": 5,
        },
        {
            "id": "c-plants",
            "title": "Water the plants",
            "group": "Garden",
            "assigneeId": None,
            "dueAt": None,
            "overdue": False,
            "state": "open",
            "requiresPhoto": False,
            "points": 3,
        },
    ],
    "goal": {
        "id": "g-1",
        "title": "Zoo trip",
        "points": 820,
        "targetPoints": 1000,
        "progress": 0.82,
    },
    "routines": [{"id": "r-bed", "name": "Bedtime hand-off", "enabled": True}],
    "updatedAt": "2026-11-25T15:00:00.000Z",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components in every test."""


@pytest.fixture
def state_payload() -> dict[str, Any]:
    """A fresh copy of the snapshot."""
    return copy.deepcopy(STATE)


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A TaskBandit config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        unique_id=HOUSEHOLD_ID,
        version=3,
        data={CONF_URL: SERVER, CONF_TOKEN: TOKEN, "hosted": True, "verify_ssl": True},
        options={"member_map": {BEA: "__not_in_ha__", TOM: "__not_in_ha__"}, "known_persons": []},
    )


async def setup_entry(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    state: dict[str, Any],
) -> None:
    """Mock /state and set up the entry."""
    aioclient_mock.get(f"{API}/state", json=state)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def calls_to(aioclient_mock: AiohttpClientMocker, method: str, path: str) -> list:
    """Mocked calls for one endpoint."""
    return [
        call
        for call in aioclient_mock.mock_calls
        if call[0].upper() == method and str(call[1]) == f"{API}{path}"
    ]
