from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTITIES, CONF_MODE, DOMAIN, MODE_TEXT
from .device import IledColorDevice
from .status_display import StatusDisplay

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            IledColorTextEntity(entry, runtime["device"], runtime["coordinator"]),
            IledColorStatusEntitiesText(entry, runtime["device"], runtime["coordinator"]),
        ]
    )


class IledColorTextEntity(TextEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "display_text"
    _attr_mode = TextMode.TEXT
    _attr_native_max = 255

    def __init__(
        self, entry: ConfigEntry, device: IledColorDevice, coordinator: StatusDisplay
    ) -> None:
        self._device = device
        self._coordinator = coordinator
        base = entry.unique_id or entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{base}_text"
        self._attr_device_info = device.device_info(base)
        self._attr_native_value = ""

    async def async_set_value(self, value: str) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
        if self._coordinator.mode != MODE_TEXT:
            await self._coordinator.async_set(**{CONF_MODE: MODE_TEXT})
        await self._coordinator.async_show_text(value)


class IledColorStatusEntitiesText(TextEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "status_entities"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = TextMode.TEXT
    _attr_native_max = 255

    def __init__(
        self, entry: ConfigEntry, device: IledColorDevice, coordinator: StatusDisplay
    ) -> None:
        self._coordinator = coordinator
        base = entry.unique_id or entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{base}_status_entities"
        self._attr_device_info = device.device_info(base)

    @property
    def native_value(self) -> str | None:
        joined = ", ".join(self._coordinator.entities)
        return joined if len(joined) <= self._attr_native_max else None

    async def async_set_value(self, value: str) -> None:
        ids = [token for token in (part.strip() for part in value.split(",")) if token]
        valid = [eid for eid in ids if self.hass.states.get(eid) is not None]
        invalid = [eid for eid in ids if eid not in valid]
        if invalid:
            _LOGGER.warning(
                "status display: unknown entities ignored: %s", ", ".join(invalid)
            )
        await self._coordinator.async_set(**{CONF_ENTITIES: valid})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.add_listener(self.async_write_ha_state))
