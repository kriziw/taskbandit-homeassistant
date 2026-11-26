"""Which Home Assistant person is which TaskBandit member.

Like mapping a robot vacuum's rooms to Home Assistant areas: every TaskBandit
member gets a Home Assistant person, or "Not in Home Assistant" (a child without
an HA account, say). People nobody picked simply aren't TaskBandit members.

The mapping is stored per member (`member_map`: member id → person entity id or
NOT_IN_HA) together with the people that existed when it was saved
(`known_persons`). It is asked for at setup, can be changed in the options, and
a repair is raised when it gets out of sync.

It decides who gets the credit: a routine button pressed or a chore ticked off
by an HA user is sent to TaskBandit as their member. It also drives presence.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_KNOWN_PERSONS, CONF_MEMBER_MAP, DOMAIN, NOT_IN_HA
from .models import TaskBanditState

NOT_IN_HA_LABEL = {
    "en": "Not in Home Assistant",
    "de": "Nicht in Home Assistant",
    "hu": "Nincs a Home Assistantban",
}


def persons(hass: HomeAssistant) -> dict[str, str]:
    """Home Assistant people: entity id → name."""
    return {
        state.entity_id: str(state.attributes.get("friendly_name") or state.entity_id)
        for state in hass.states.async_all("person")
    }


def member_map(options: dict[str, Any]) -> dict[str, str]:
    """The stored mapping: member id → person entity id or NOT_IN_HA."""
    return dict(options.get(CONF_MEMBER_MAP) or {})


def person_to_member(options: dict[str, Any]) -> dict[str, str]:
    """Mapped people: person entity id → member id."""
    return {
        person: member
        for member, person in member_map(options).items()
        if person and person != NOT_IN_HA
    }


def member_for_context(
    hass: HomeAssistant, options: dict[str, Any], context: Context | None
) -> str | None:
    """The TaskBandit member of the HA user behind an action, if mapped."""
    user_id = context.user_id if context else None
    if not user_id:
        return None
    mapped = person_to_member(options)
    for state in hass.states.async_all("person"):
        if state.attributes.get("user_id") == user_id and state.entity_id in mapped:
            return mapped[state.entity_id]
    return None


def _labels(state: TaskBanditState) -> dict[str, str]:
    """Form field label per member id: the member's name, unique within the form."""
    labels: dict[str, str] = {}
    used: set[str] = set()
    for member_id, member in state.members.items():
        label = member.display_name
        count = 2
        while label in used:
            label = f"{member.display_name} ({count})"
            count += 1
        used.add(label)
        labels[member_id] = label
    return labels


def _suggest(member_name: str, people: dict[str, str], taken: set[str]) -> str:
    """Pick the person whose name matches the member's (full or first name)."""
    wanted = member_name.casefold().strip()
    first = wanted.split(" ")[0] if wanted else ""
    for match in (
        lambda name: name == wanted,
        lambda name: bool(first) and name.split(" ")[0] == first,
    ):
        for entity_id, name in people.items():
            if entity_id not in taken and match(name.casefold().strip()):
                return entity_id
    return NOT_IN_HA


def mapping_schema(
    hass: HomeAssistant, state: TaskBanditState, options: dict[str, Any]
) -> vol.Schema:
    """One dropdown per TaskBandit member: an HA person or "Not in Home Assistant"."""
    people = persons(hass)
    current = member_map(options)
    language = (hass.config.language or "en").split("-")[0]
    choices = [
        SelectOptionDict(value=NOT_IN_HA, label=NOT_IN_HA_LABEL.get(language, NOT_IN_HA_LABEL["en"]))
    ] + [SelectOptionDict(value=entity_id, label=name) for entity_id, name in sorted(people.items(), key=lambda item: item[1].casefold())]
    taken = {person for person in current.values() if person in people}
    fields: dict[Any, Any] = {}
    for member_id, label in _labels(state).items():
        stored = current.get(member_id)
        if stored == NOT_IN_HA or stored in people:
            default = stored
        else:
            default = _suggest(state.members[member_id].display_name, people, taken)
            if default != NOT_IN_HA:
                taken.add(default)
        fields[vol.Required(label, default=default)] = SelectSelector(
            SelectSelectorConfig(options=choices, mode=SelectSelectorMode.DROPDOWN)
        )
    return vol.Schema(fields)


def mapping_from_input(
    hass: HomeAssistant, state: TaskBanditState, user_input: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Turn the form into options (`member_map`, `known_persons`), or a form error."""
    mapping: dict[str, str] = {}
    for member_id, label in _labels(state).items():
        mapping[member_id] = str(user_input.get(label) or NOT_IN_HA)
    chosen = [person for person in mapping.values() if person != NOT_IN_HA]
    if len(chosen) != len(set(chosen)):
        return {}, {"base": "person_used_twice"}
    return {CONF_MEMBER_MAP: mapping, CONF_KNOWN_PERSONS: sorted(persons(hass))}, {}


def mapping_problems(
    hass: HomeAssistant, state: TaskBanditState, options: dict[str, Any]
) -> list[str]:
    """Why the mapping is out of sync; empty when it is fine.

    - `member_removed`: a mapped member is no longer in TaskBandit
    - `person_removed`: a mapped person is no longer in Home Assistant
    - `member_added`: a TaskBandit member nobody has decided about yet
    - `person_added`: a new HA person while some member is "Not in Home Assistant",
      who might be them
    """
    mapping = member_map(options)
    people = set(persons(hass))
    known = set(options.get(CONF_KNOWN_PERSONS) or [])
    problems: list[str] = []
    if any(member not in state.members for member in mapping):
        problems.append("member_removed")
    if any(person != NOT_IN_HA and person not in people for person in mapping.values()):
        problems.append("person_removed")
    if any(member not in mapping for member in state.members):
        problems.append("member_added")
    unmatched_member = any(person == NOT_IN_HA for person in mapping.values())
    new_people = people - known - set(mapping.values())
    if unmatched_member and new_people:
        problems.append("person_added")
    return problems


def issue_id(entry_id: str) -> str:
    """The repair issue for an entry's mapping."""
    return f"member_mapping_{entry_id}"


@callback
def async_check_mapping(
    hass: HomeAssistant, entry_id: str, title: str, state: TaskBanditState, options: dict[str, Any]
) -> None:
    """Raise or clear the "map members" repair."""
    if mapping_problems(hass, state, options):
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id(entry_id),
            data={"entry_id": entry_id},
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="member_mapping",
            translation_placeholders={"household": title},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id(entry_id))
