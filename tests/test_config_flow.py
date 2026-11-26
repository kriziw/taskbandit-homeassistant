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

USER_INPUT = {CONF_URL: "https://tb.example.com/", CONF_TOKEN: f" {TOKEN} "}
ENTRY_DATA = {CONF_URL: SERVER, CONF_TOKEN: TOKEN, "hosted": False, "verify_ssl": True}


async def _start(hass: HomeAssistant, option: str = "self_hosted") -> str:
    """Open the flow and pick Cloud or Self-hosted from the menu."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {"cloud", "self_hosted"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": option}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == option
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
    assert result["data"] == ENTRY_DATA
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


async def test_options_flow_maps_members(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    state_payload,
) -> None:
    """Configure shows one dropdown per TaskBandit member, named after them."""
    hass.states.async_set("person.bea", "home", {"friendly_name": "Bea"})
    hass.states.async_set("person.tom", "not_home", {"friendly_name": "Tom"})
    aioclient_mock.put(f"{API}/presence", status=204)
    await setup_entry(hass, config_entry, aioclient_mock, state_payload)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    keys = {str(key) for key in result["data_schema"].schema}
    assert keys == {"scan_interval", "Bea", "Tom"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 120, "Bea": "person.bea", "Tom": "__not_in_ha__"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_SCAN_INTERVAL] == 120
    assert config_entry.options["member_map"] == {BEA: "person.bea", "m-tom": "__not_in_ha__"}
    assert config_entry.options["known_persons"] == ["person.bea", "person.tom"]


async def test_options_flow_one_person_per_member(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    state_payload,
) -> None:
    """The same person can't be two members."""
    hass.states.async_set("person.bea", "home", {"friendly_name": "Bea"})
    await setup_entry(hass, config_entry, aioclient_mock, state_payload)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60, "Bea": "person.bea", "Tom": "person.bea"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "person_used_twice"}


CLOUD_API = "https://api.taskbandit.app/api/integrations/home-assistant"


async def test_cloud_flow_needs_only_the_token(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, state_payload
) -> None:
    """TaskBandit Cloud: the token alone sets it up."""
    aioclient_mock.get(f"{CLOUD_API}/state", json=state_payload)
    flow_id = await _start(hass, "cloud")
    with patch("custom_components.taskbandit.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(flow_id, {CONF_TOKEN: TOKEN})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_URL: "https://api.taskbandit.app",
        CONF_TOKEN: TOKEN,
        "hosted": True,
        "verify_ssl": True,
    }


async def test_self_hosted_keeps_http_and_can_skip_cert_check(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, state_payload
) -> None:
    """A LAN address without a scheme becomes http, and verify_ssl is stored."""
    aioclient_mock.get(
        "http://192.168.1.10:8080/api/integrations/home-assistant/state", json=state_payload
    )
    flow_id = await _start(hass)
    with patch("custom_components.taskbandit.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_URL: "192.168.1.10:8080", CONF_TOKEN: TOKEN, "verify_ssl": False}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_URL] == "http://192.168.1.10:8080"
    assert result["data"]["verify_ssl"] is False
    assert result["data"]["hosted"] is False


def _zeroconf_info(host: str, port: int, properties: dict[str, str]):
    from ipaddress import ip_address

    try:
        from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
    except ImportError:  # Older Home Assistant without the zeroconf library installed
        from types import SimpleNamespace

        return SimpleNamespace(
            host=host, ip_address=ip_address(host), port=port, properties=properties
        )

    return ZeroconfServiceInfo(
        ip_address=ip_address(host),
        ip_addresses=[ip_address(host)],
        hostname="taskbandit.local.",
        name="TaskBandit._taskbandit._tcp.local.",
        port=port,
        type="_taskbandit._tcp.local.",
        properties=properties,
    )


async def test_zeroconf_discovery_fills_in_the_address(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, state_payload
) -> None:
    """A discovered server only needs the token."""
    aioclient_mock.get(
        "http://192.168.1.10:8080/api/integrations/home-assistant/state", json=state_payload
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zeroconf_info("192.168.1.10", 8080, {"path": "/", "version": "1.27.0"}),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "self_hosted"
    schema_defaults = {
        str(key): key.description.get("suggested_value")
        for key in result["data_schema"].schema
        if getattr(key, "description", None)
    }
    assert schema_defaults[CONF_URL] == "http://192.168.1.10:8080"
    with patch("custom_components.taskbandit.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_URL: "http://192.168.1.10:8080", CONF_TOKEN: TOKEN, "verify_ssl": True},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == HOUSEHOLD_ID


async def test_zeroconf_prefers_the_announced_api_address(hass: HomeAssistant) -> None:
    """The server's announced address wins over where the announcement came from."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zeroconf_info("172.18.0.3", 8080, {"api": "https://tasks.home.lan"}),
    )
    defaults = {
        str(key): key.description.get("suggested_value")
        for key in result["data_schema"].schema
        if getattr(key, "description", None)
    }
    assert defaults[CONF_URL] == "https://tasks.home.lan"


async def test_zeroconf_ignores_a_configured_server(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A server that is already set up isn't offered again."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zeroconf_info("127.0.0.1", 8080, {"api": SERVER}),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_version_1_entries_are_migrated(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, state_payload
) -> None:
    """Old entries learn whether they are TaskBandit Cloud."""
    aioclient_mock.get(f"{CLOUD_API}/state", json=state_payload)
    aioclient_mock.put(f"{CLOUD_API}/webhook", json={"secret": "whsec_x", "events": []})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        unique_id=HOUSEHOLD_ID,
        version=1,
        data={CONF_URL: "https://api.taskbandit.app", CONF_TOKEN: TOKEN},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.version == 3
    assert entry.data["hosted"] is True
    assert entry.data["verify_ssl"] is True


async def test_setup_asks_who_is_who_and_suggests_by_name(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, state_payload
) -> None:
    """After the token, each member gets a person; names that match are suggested."""
    hass.states.async_set("person.bea_smith", "home", {"friendly_name": "Bea Smith"})
    hass.states.async_set("person.guest", "home", {"friendly_name": "Guest"})
    aioclient_mock.get(f"{CLOUD_API}/state", json=state_payload)
    flow_id = await _start(hass, "cloud")
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_TOKEN: TOKEN})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "members"
    defaults = {str(key): key.default() for key in result["data_schema"].schema}
    assert defaults == {"Bea": "person.bea_smith", "Tom": "__not_in_ha__"}
    with patch("custom_components.taskbandit.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"Bea": "person.bea_smith", "Tom": "__not_in_ha__"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["member_map"] == {BEA: "person.bea_smith", "m-tom": "__not_in_ha__"}
    # The guest isn't a member and isn't asked about again.
    assert sorted(result["options"]["known_persons"]) == ["person.bea_smith", "person.guest"]


async def test_setup_without_people_skips_the_mapping(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, state_payload
) -> None:
    """With no people in Home Assistant there is nothing to ask."""
    aioclient_mock.get(f"{CLOUD_API}/state", json=state_payload)
    flow_id = await _start(hass, "cloud")
    with patch("custom_components.taskbandit.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(flow_id, {CONF_TOKEN: TOKEN})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert set(result["options"]["member_map"].values()) == {"__not_in_ha__"}
