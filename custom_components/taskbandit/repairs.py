"""Repairs for TaskBandit: re-map members when the mapping gets out of sync."""

from __future__ import annotations

from typing import Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant

from .members import mapping_from_input, mapping_schema


class MemberMappingRepairFlow(RepairsFlow):
    """Shows the member ↔ person form and saves it to the entry's options."""

    def __init__(self, entry_id: str) -> None:
        """Remember which entry to fix."""
        self._entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Ask again which person is which member."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        runtime = getattr(entry, "runtime_data", None) if entry else None
        state = runtime.coordinator.data if runtime is not None else None
        if entry is None or state is None:
            return self.async_abort(reason="not_loaded")

        errors: dict[str, str] = {}
        if user_input is not None:
            mapping, errors = mapping_from_input(self.hass, state, user_input)
            if not errors:
                self.hass.config_entries.async_update_entry(
                    entry, options={**entry.options, **mapping}
                )
                return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="init",
            data_schema=mapping_schema(self.hass, state, dict(entry.options)),
            errors=errors,
            description_placeholders={"household": entry.title},
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    """Create the flow for a TaskBandit repair."""
    if issue_id.startswith("member_mapping_") and data and "entry_id" in data:
        return MemberMappingRepairFlow(str(data["entry_id"]))
    return ConfirmRepairFlow()
