"""Webhook push tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.taskbandit.const import (
    CONF_WEBHOOK_SECRET,
    EVENT_ROUTINE_STEP,
    EVENT_TASKBANDIT,
)
from custom_components.taskbandit.push import verify_signature

from .conftest import API, calls_to, setup_entry

SECRET = "whsec_test"


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return f"sha256={digest.hexdigest()}"


def test_signature_valid() -> None:
    """A correct, fresh signature passes."""
    body = b'{"type":"ping"}'
    ts = str(int(time.time()))
    assert verify_signature(SECRET, ts, body, _sign(SECRET, ts, body))


def test_signature_invalid() -> None:
    """A wrong secret, tampered body or missing header fails."""
    body = b'{"type":"ping"}'
    ts = str(int(time.time()))
    assert not verify_signature(SECRET, ts, body, _sign("whsec_other", ts, body))
    assert not verify_signature(SECRET, ts, b'{"type":"pong"}', _sign(SECRET, ts, body))
    assert not verify_signature(SECRET, ts, body, None)
    assert not verify_signature(SECRET, None, body, _sign(SECRET, ts, body))
    assert not verify_signature(SECRET, "abc", body, _sign(SECRET, "abc", body))


def test_signature_stale() -> None:
    """A signature older than five minutes fails."""
    body = b'{"type":"ping"}'
    ts = str(int(time.time()) - 301)
    assert not verify_signature(SECRET, ts, body, _sign(SECRET, ts, body))
    now = 1_800_000_000
    ts = str(now)
    assert verify_signature(SECRET, ts, body, _sign(SECRET, ts, body), now=now + 299)
    assert not verify_signature(SECRET, ts, body, _sign(SECRET, ts, body), now=now + 300)


async def test_push_end_to_end(
    hass: HomeAssistant,
    hass_client_no_auth,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    state_payload,
) -> None:
    """Setup registers the webhook; signed pushes fire events, bad ones are refused."""
    await async_process_ha_core_config(hass, {"external_url": "https://ha.example.com"})
    aioclient_mock.put(
        f"{API}/webhook", json={"secret": SECRET, "events": ["chore.completed"]}
    )
    aioclient_mock.delete(f"{API}/webhook", status=204)
    await setup_entry(hass, config_entry, aioclient_mock, state_payload)

    webhook_id = config_entry.data[CONF_WEBHOOK_ID]
    assert config_entry.data[CONF_WEBHOOK_SECRET] == SECRET
    put = calls_to(aioclient_mock, "PUT", "/webhook")
    assert put[0][2] == {"url": f"https://ha.example.com/api/webhook/{webhook_id}"}

    events = async_capture_events(hass, EVENT_TASKBANDIT)
    steps = async_capture_events(hass, EVENT_ROUTINE_STEP)
    client = await hass_client_no_auth()

    async def post(payload: dict, *, secret: str = SECRET, age: int = 0, delivery: str = "d1"):
        body = json.dumps(payload).encode()
        ts = str(int(time.time()) - age)
        return await client.post(
            f"/api/webhook/{webhook_id}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-TaskBandit-Timestamp": ts,
                "X-TaskBandit-Signature": _sign(secret, ts, body),
                "X-TaskBandit-Delivery": delivery,
            },
        )

    completed = {
        "id": "d1",
        "type": "chore.completed",
        "occurredAt": "2026-11-25T15:00:00.000Z",
        "household": {"id": "hh-1", "name": "Home"},
        "data": {"chore": {"id": "c-dish", "title": "Empty the dishwasher"}},
    }
    resp = await post(completed)
    assert resp.status == 200
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["type"] == "chore.completed"
    assert events[0].data["data"]["chore"]["id"] == "c-dish"

    # A retry of the same delivery is accepted but not fired again.
    assert (await post(completed)).status == 200
    await hass.async_block_till_done()
    assert len(events) == 1

    # Wrong secret and stale timestamps are refused.
    assert (await post(completed, secret="whsec_wrong", delivery="d2")).status == 401
    assert (await post(completed, age=600, delivery="d3")).status == 401
    await hass.async_block_till_done()
    assert len(events) == 1

    step = {
        "id": "d4",
        "type": "home_assistant.event",
        "data": {
            "label": "kitchen_light",
            "routine": {"id": "r-bed", "name": "After school"},
            "runner": {"id": "m-bea", "displayName": "Bea"},
        },
    }
    assert (await post(step, delivery="d4")).status == 200
    await hass.async_block_till_done()
    assert len(events) == 2
    assert len(steps) == 1
    assert steps[0].data["label"] == "kitchen_light"
    assert steps[0].data["routine"]["name"] == "After school"
    assert steps[0].data["runner"]["displayName"] == "Bea"

    # Unloading removes the webhook from TaskBandit.
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert len(calls_to(aioclient_mock, "DELETE", "/webhook")) == 1


async def test_no_external_url_polls_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    state_payload,
) -> None:
    """Without an external URL nothing is registered."""
    await setup_entry(hass, config_entry, aioclient_mock, state_payload)
    assert not calls_to(aioclient_mock, "PUT", "/webhook")
    assert CONF_WEBHOOK_SECRET not in config_entry.data
