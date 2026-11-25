"""Config and options flow tests."""

from __future__ import annotations

from unittest.mock import patch

import aiohttp

from homeassistant import config_entries
from homeassistant.const import CONF_SCAN_INTERVAL, CONF_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.taskbandit.const import CONF_PRESENCE_MAP, DOMAIN

from .conftest import API, BEA, HOUSEHOLD_ID, SERVER, TOKEN, setup_entry

USER_INPUT = {CONF_URL: "tb.example.com/", CONF_TOKEN: f" {TOKEN} "}


async def _start(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return result["flow_id"]


async def test_user_flow_success(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, state_payload
) -> None:
    """A valid token creates an entry keyed by the household."""
    aioclient_mock.get(f"{API}/state", json=state_payload)
    flow_id = await _start(hass)
    with patch("custom_components.taskbandit.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home"
    assert result["data"] == {CONF_URL: SERVER, CONF_TOKEN: TOKEN}
    assert result["result"].unique_id == HOUSEHOLD_ID
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == f"Bearer {TOKEN}"


async def test_user_flow_invalid_token(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 401 shows invalid_auth."""
    aioclient_mock.get(f"{API}/state", status=401, json={"message": "Unauthorized"})
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_feature_disabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """403 package_feature_disabled shows feature_disabled."""
    aioclient_mock.get(
        f"{API}/state",
        status=403,
        json={"code": "package_feature_disabled", "message": "home_assistant is off"},
    )
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["errors"] == {"base": "feature_disabled"}


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A connection error shows cannot_connect."""
    aioclient_mock.get(f"{API}/state", exc=aiohttp.ClientConnectionError())
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    state_payload,
) -> None:
    """The same household can't be added twice."""
    config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{API}/state", json=state_payload)
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    state_payload,
) -> None:
    """Reauth stores the new token."""
    config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{API}/state", json=state_payload)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    with patch("custom_components.taskbandit.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TOKEN: "tbha_new"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_TOKEN] == "tbha_new"


async def test_options_flow_presence(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    state_payload,
) -> None:
    """Persons can be mapped to members while presence is on."""
    hass.states.async_set("person.bea", "home")
    hass.states.async_set("person.tom", "not_home")
    aioclient_mock.put(f"{API}/presence", status=204)
    await setup_entry(hass, config_entry, aioclient_mock, state_payload)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    keys = {str(key) for key in result["data_schema"].schema}
    assert {"scan_interval", "person.bea", "person.tom"} <= keys

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 120, "person.bea": BEA, "person.tom": "__none__"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        CONF_SCAN_INTERVAL: 120,
        CONF_PRESENCE_MAP: {"person.bea": BEA},
    }


async def test_options_flow_without_presence(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    state_payload,
) -> None:
    """No person fields while presence is off."""
    state_payload["presenceEnabled"] = False
    hass.states.async_set("person.bea", "home")
    await setup_entry(hass, config_entry, aioclient_mock, state_payload)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    keys = {str(key) for key in result["data_schema"].schema}
    assert keys == {"scan_interval"}
