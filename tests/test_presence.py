"""Presence reporting tests."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.taskbandit.const import DOMAIN

from .conftest import API, BEA, HOUSEHOLD_ID, SERVER, TOKEN, TOM, calls_to, setup_entry


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        unique_id=HOUSEHOLD_ID,
        version=3,
        data={CONF_URL: SERVER, CONF_TOKEN: TOKEN, "hosted": True, "verify_ssl": True},
        options={
            "member_map": {BEA: "person.bea", TOM: "person.tom"},
            "known_persons": ["person.bea", "person.tom"],
        },
    )


async def test_presence_reported(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, state_payload
) -> None:
    """All mapped members are sent on startup, then each change."""
    hass.states.async_set("person.bea", "home")
    hass.states.async_set("person.tom", "not_home")
    aioclient_mock.put(f"{API}/presence", status=204)
    await setup_entry(hass, _entry(), aioclient_mock, state_payload)

    calls = calls_to(aioclient_mock, "PUT", "/presence")
    assert len(calls) == 1
    assert calls[0][2] == {
        "members": [{"memberId": BEA, "home": True}, {"memberId": TOM, "home": False}]
    }

    hass.states.async_set("person.bea", "work")
    await hass.async_block_till_done()
    calls = calls_to(aioclient_mock, "PUT", "/presence")
    assert calls[-1][2] == {"members": [{"memberId": BEA, "home": False}]}

    # Moving between two away zones isn't a change.
    hass.states.async_set("person.bea", "school")
    await hass.async_block_till_done()
    assert len(calls_to(aioclient_mock, "PUT", "/presence")) == 2

    hass.states.async_set("person.tom", "home")
    await hass.async_block_till_done()
    calls = calls_to(aioclient_mock, "PUT", "/presence")
    assert calls[-1][2] == {"members": [{"memberId": TOM, "home": True}]}

    # Unmapped persons are ignored.
    hass.states.async_set("person.guest", "home")
    await hass.async_block_till_done()
    assert len(calls_to(aioclient_mock, "PUT", "/presence")) == 3


async def test_presence_disabled_is_graceful(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, state_payload
) -> None:
    """409 presence_disabled doesn't break anything."""
    hass.states.async_set("person.bea", "home")
    aioclient_mock.put(f"{API}/presence", status=409, json={"code": "presence_disabled"})
    entry = _entry()
    await setup_entry(hass, entry, aioclient_mock, state_payload)
    assert entry.state is ConfigEntryState.LOADED
    hass.states.async_set("person.bea", "not_home")
    await hass.async_block_till_done()
    assert len(calls_to(aioclient_mock, "PUT", "/presence")) == 2
    assert entry.runtime_data.presence_disabled_logged is True
