"""The TaskBandit integration."""

from __future__ import annotations

from urllib.parse import urlparse

from homeassistant.const import CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import TaskBanditClient
from .const import CLOUD_URL, CONF_HOSTED, DOMAIN, LOGGER
from .coordinator import TaskBanditConfigEntry, TaskBanditCoordinator, TaskBanditRuntimeData
from .presence import async_setup_presence
from .push import async_remove_push, async_setup_push, async_teardown_push
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.TODO,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the TaskBandit services."""
    async_setup_services(hass)
    return True


def _client(hass: HomeAssistant, entry: TaskBanditConfigEntry) -> TaskBanditClient:
    """An API client for the entry (self-hosted servers may use a self-signed certificate)."""
    return TaskBanditClient(
        async_get_clientsession(hass, verify_ssl=entry.data.get(CONF_VERIFY_SSL, True)),
        entry.data[CONF_URL],
        entry.data[CONF_TOKEN],
    )


async def async_migrate_entry(hass: HomeAssistant, entry: TaskBanditConfigEntry) -> bool:
    """Version 1 entries had only an address: record whether it is TaskBandit Cloud."""
    if entry.version == 1:
        hosted = urlparse(entry.data[CONF_URL]).hostname == urlparse(CLOUD_URL).hostname
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_HOSTED: hosted, CONF_VERIFY_SSL: True},
            version=2,
        )
        LOGGER.debug("Migrated TaskBandit entry %s to version 2", entry.entry_id)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TaskBanditConfigEntry) -> bool:
    """Set up TaskBandit from a config entry."""
    client = _client(hass, entry)
    coordinator = TaskBanditCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = TaskBanditRuntimeData(
        client=client, coordinator=coordinator, options=dict(entry.options)
    )

    await async_setup_push(hass, entry)
    async_setup_presence(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: TaskBanditConfigEntry) -> None:
    """Reload when the options change (data updates such as the secret don't)."""
    if dict(entry.options) != entry.runtime_data.options:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TaskBanditConfigEntry) -> bool:
    """Unload a config entry."""
    await async_teardown_push(hass, entry)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: TaskBanditConfigEntry) -> None:
    """Remove the TaskBandit webhook when the entry is deleted."""
    client = _client(hass, entry)
    await async_remove_push(hass, entry, client)
