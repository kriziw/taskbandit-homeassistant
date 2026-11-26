"""Member ↔ person mapping: sync checks, the repair, and crediting the right member."""

from __future__ import annotations

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import issue_registry as ir

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.taskbandit.const import DOMAIN, NOT_IN_HA
from custom_components.taskbandit.members import (
    issue_id,
    mapping_problems,
    member_for_context,
)
from custom_components.taskbandit.models import parse_state

from .conftest import API, BEA, HOUSEHOLD_ID, SERVER, STATE, TOKEN, TOM, setup_entry


def _entry(options: dict) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        unique_id=HOUSEHOLD_ID,
        version=3,
        data={"url": SERVER, "token": TOKEN, "hosted": True, "verify_ssl": True},
        options=options,
    )

STATE_PARSED = parse_state(STATE)


def _people(hass: HomeAssistant, **people: str | None) -> None:
    for entity_id, user_id in people.items():
        hass.states.async_set(
            f"person.{entity_id}", "home", {"friendly_name": entity_id.title(), "user_id": user_id}
        )


async def test_in_sync(hass: HomeAssistant) -> None:
    """Everyone decided, nobody new: nothing to fix."""
    _people(hass, bea="u-bea", guest=None)
    options = {
        "member_map": {BEA: "person.bea", TOM: NOT_IN_HA},
        "known_persons": ["person.bea", "person.guest"],
    }
    assert mapping_problems(hass, STATE_PARSED, options) == []


async def test_out_of_sync_reasons(hass: HomeAssistant) -> None:
    """Removed or new members and people are each noticed."""
    _people(hass, bea="u-bea", newbie=None)
    options = {
        "member_map": {BEA: "person.bea", "m-gone": "person.gone", TOM: NOT_IN_HA},
        "known_persons": ["person.bea"],
    }
    assert mapping_problems(hass, STATE_PARSED, options) == [
        "member_removed",
        "person_removed",
        "person_added",
    ]
    assert mapping_problems(hass, STATE_PARSED, {"member_map": {BEA: "person.bea"}}) == [
        "member_added"
    ]


async def test_new_person_ignored_when_every_member_has_one(hass: HomeAssistant) -> None:
    """A new HA person who can't be anyone (all members matched) isn't a problem."""
    _people(hass, bea="u-bea", tom="u-tom", visitor=None)
    options = {
        "member_map": {BEA: "person.bea", TOM: "person.tom"},
        "known_persons": ["person.bea", "person.tom"],
    }
    assert mapping_problems(hass, STATE_PARSED, options) == []


async def test_member_for_context(hass: HomeAssistant) -> None:
    """An HA user is credited as their person's member."""
    _people(hass, bea="u-bea", tom="u-tom")
    options = {"member_map": {BEA: "person.bea", TOM: NOT_IN_HA}}
    assert member_for_context(hass, options, Context(user_id="u-bea")) == BEA
    assert member_for_context(hass, options, Context(user_id="u-tom")) is None
    assert member_for_context(hass, options, Context()) is None


async def test_repair_raised_and_fixed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, state_payload
) -> None:
    """A member nobody decided about raises the repair; fixing it clears it."""
    config_entry = _entry({"member_map": {BEA: NOT_IN_HA}, "known_persons": []})
    await setup_entry(hass, config_entry, aioclient_mock, state_payload)
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, issue_id(config_entry.entry_id)) is not None

    from custom_components.taskbandit.repairs import async_create_fix_flow

    flow = await async_create_fix_flow(
        hass, issue_id(config_entry.entry_id), {"entry_id": config_entry.entry_id}
    )
    flow.hass = hass
    result = await flow.async_step_init()
    assert {str(key) for key in result["data_schema"].schema} == {"Bea", "Tom"}
    result = await flow.async_step_init({"Bea": NOT_IN_HA, "Tom": NOT_IN_HA})
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert config_entry.options["member_map"] == {BEA: NOT_IN_HA, TOM: NOT_IN_HA}


async def test_ticking_off_credits_the_users_member(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, state_payload
) -> None:
    """The member of the HA user who ticked the item off is sent along."""
    user = await hass.auth.async_create_user("Bea")
    hass.states.async_set("person.bea", "home", {"friendly_name": "Bea", "user_id": user.id})
    config_entry = _entry(
        {"member_map": {BEA: "person.bea", TOM: NOT_IN_HA}, "known_persons": ["person.bea"]}
    )
    aioclient_mock.put(f"{API}/presence", status=204)
    await setup_entry(hass, config_entry, aioclient_mock, state_payload)
    aioclient_mock.post(f"{API}/chores/c-plants/complete", json={"outcome": "completed"})
    todo = next(
        entity_id
        for entity_id in hass.states.async_entity_ids("todo")
        if "unassigned" in entity_id
    )
    await hass.services.async_call(
        "todo",
        "update_item",
        {"item": "c-plants", "status": "completed"},
        target={"entity_id": todo},
        blocking=True,
        context=Context(user_id=user.id),
    )
    call = next(c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/chores/c-plants/complete"))
    assert call[2] == {"memberId": BEA}
