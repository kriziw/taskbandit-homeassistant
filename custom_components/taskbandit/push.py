"""Webhook push from TaskBandit to Home Assistant."""

from __future__ import annotations

from functools import partial
import hashlib
import hmac
from http import HTTPStatus
import json
import time

from aiohttp import web

from homeassistant.components import webhook
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .api import TaskBanditClient, TaskBanditError, TaskBanditScopeError
from .const import (
    CONF_CLOUDHOOK,
    CONF_WEBHOOK_SECRET,
    DOMAIN,
    EVENT_ROUTINE_STEP,
    EVENT_TASKBANDIT,
    HA_EVENT_TYPE,
    HEADER_DELIVERY,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    LOGGER,
    SIGNATURE_MAX_AGE,
)
from .coordinator import TaskBanditConfigEntry, async_report_missing_scope


def verify_signature(
    secret: str,
    timestamp: str | None,
    raw_body: bytes,
    signature: str | None,
    now: float | None = None,
) -> bool:
    """Check `sha256=<hex HMAC-SHA256 of "<timestamp>.<raw body>">` and freshness."""
    if not secret or not timestamp or not signature:
        return False
    try:
        sent_at = float(timestamp)
    except ValueError:
        return False
    if now is None:
        now = time.time()
    if abs(now - sent_at) >= SIGNATURE_MAX_AGE:
        return False
    digest = hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={digest}", signature.strip())


async def _async_webhook_url(
    hass: HomeAssistant, webhook_id: str
) -> tuple[str | None, bool]:
    """Return the URL TaskBandit should call, and whether it is a cloudhook."""
    if "cloud" in hass.config.components:
        from homeassistant.components import cloud  # noqa: PLC0415

        try:
            if cloud.async_active_subscription(hass) and cloud.async_is_connected(hass):
                return await cloud.async_get_or_create_cloudhook(hass, webhook_id), True
        except Exception as err:  # noqa: BLE001
            LOGGER.debug("Could not create a Home Assistant Cloud webhook: %s", err)
    try:
        base = get_url(hass, prefer_external=True, allow_internal=False)
    except NoURLAvailableError:
        return None, False
    return f"{base}{webhook.async_generate_path(webhook_id)}", False


async def async_setup_push(hass: HomeAssistant, entry: TaskBanditConfigEntry) -> None:
    """Register an HA webhook and tell TaskBandit about it."""
    runtime = entry.runtime_data
    webhook_id = entry.data.get(CONF_WEBHOOK_ID) or webhook.async_generate_id()
    url, is_cloudhook = await _async_webhook_url(hass, webhook_id)
    if url is None:
        LOGGER.info(
            "Home Assistant has no external URL, so TaskBandit can't push changes; "
            "polling only"
        )
        return

    webhook.async_register(
        hass,
        DOMAIN,
        f"TaskBandit ({entry.title})",
        webhook_id,
        partial(_async_handle_webhook, entry.entry_id),
        local_only=False,
        allowed_methods=["POST"],
    )
    runtime.webhook_id = webhook_id

    try:
        result = await runtime.client.set_webhook(url)
    except TaskBanditScopeError as err:
        async_report_missing_scope(hass, entry, err.scope)
        _unregister(hass, runtime)
        return
    except TaskBanditError as err:
        LOGGER.warning(
            "Could not register the TaskBandit webhook (%s); polling only", err
        )
        _unregister(hass, runtime)
        return

    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_WEBHOOK_ID: webhook_id,
            CONF_WEBHOOK_SECRET: result["secret"],
            CONF_CLOUDHOOK: is_cloudhook,
        },
    )
    LOGGER.debug("TaskBandit push registered at %s", url)


def _unregister(hass: HomeAssistant, runtime) -> None:
    if runtime.webhook_id:
        webhook.async_unregister(hass, runtime.webhook_id)
        runtime.webhook_id = None


async def async_teardown_push(
    hass: HomeAssistant, entry: TaskBanditConfigEntry
) -> None:
    """Unregister the HA webhook and remove it from TaskBandit."""
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None or runtime.webhook_id is None:
        return
    _unregister(hass, runtime)
    try:
        await runtime.client.delete_webhook()
    except TaskBanditError as err:
        LOGGER.debug("Could not remove the TaskBandit webhook: %s", err)


async def async_remove_push(
    hass: HomeAssistant, entry: TaskBanditConfigEntry, client: TaskBanditClient
) -> None:
    """Clean up after the config entry is removed."""
    try:
        await client.delete_webhook()
    except TaskBanditError as err:
        LOGGER.debug("Could not remove the TaskBandit webhook: %s", err)
    webhook_id = entry.data.get(CONF_WEBHOOK_ID)
    if entry.data.get(CONF_CLOUDHOOK) and webhook_id and "cloud" in hass.config.components:
        from homeassistant.components import cloud  # noqa: PLC0415

        try:
            await cloud.async_delete_cloudhook(hass, webhook_id)
        except Exception as err:  # noqa: BLE001
            LOGGER.debug("Could not delete the cloudhook: %s", err)


async def _async_handle_webhook(
    entry_id: str, hass: HomeAssistant, webhook_id: str, request: web.Request
) -> web.Response:
    """Verify and dispatch one pushed TaskBandit event."""
    entry: TaskBanditConfigEntry | None = hass.config_entries.async_get_entry(entry_id)
    if entry is None or not hasattr(entry, "runtime_data"):
        return web.Response(status=HTTPStatus.NOT_FOUND)
    raw = await request.read()
    secret = entry.data.get(CONF_WEBHOOK_SECRET)
    if not secret or not verify_signature(
        secret,
        request.headers.get(HEADER_TIMESTAMP),
        raw,
        request.headers.get(HEADER_SIGNATURE),
    ):
        LOGGER.warning("Rejected a TaskBandit push with a missing, wrong or stale signature")
        return web.Response(status=HTTPStatus.UNAUTHORIZED)

    try:
        payload = json.loads(raw)
    except ValueError:
        return web.Response(status=HTTPStatus.BAD_REQUEST)
    if not isinstance(payload, dict) or not isinstance(payload.get("type"), str):
        return web.Response(status=HTTPStatus.BAD_REQUEST)

    runtime = entry.runtime_data
    delivery = request.headers.get(HEADER_DELIVERY) or payload.get("id")
    if isinstance(delivery, str) and delivery:
        if delivery in runtime.seen_deliveries:
            return web.Response(status=HTTPStatus.OK)
        runtime.seen_deliveries.append(delivery)

    event_type: str = payload["type"]
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    hass.bus.async_fire(
        EVENT_TASKBANDIT,
        {
            "config_entry_id": entry.entry_id,
            "id": payload.get("id"),
            "type": event_type,
            "occurred_at": payload.get("occurredAt"),
            "data": data,
        },
    )
    if event_type == HA_EVENT_TYPE:
        hass.bus.async_fire(
            EVENT_ROUTINE_STEP,
            {
                "config_entry_id": entry.entry_id,
                "label": data.get("label"),
                "routine": data.get("routine"),
                "runner": data.get("runner"),
            },
        )
    await runtime.coordinator.async_request_refresh()
    return web.Response(status=HTTPStatus.OK)
