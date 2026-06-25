from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import IledColorDevice


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    device: IledColorDevice = hass.data[DOMAIN][entry.entry_id]["device"]
    async_add_entities([IledColorTextEntity(entry, device)])


class IledColorTextEntity(TextEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "display_text"
    _attr_mode = TextMode.TEXT
    _attr_native_max = 255

    def __init__(self, entry: ConfigEntry, device: IledColorDevice) -> None:
        self._device = device
        base = entry.unique_id or entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{base}_text"
        self._attr_device_info = device.device_info(base)
        self._attr_native_value = ""

    async def async_set_value(self, value: str) -> None:
        await self._device.display_text(value)
        self._attr_native_value = value
        self.async_write_ha_state()
