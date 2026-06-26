from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_MODE, DOMAIN, MODE_TEXT
from .device import IledColorDevice
from .status_display import StatusDisplay


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([IledColorTextEntity(entry, runtime["device"], runtime["coordinator"])])


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
        self._coordinator.last_text = value
        if not self._device.power_on:
            return
        await self._device.display_text(
            value,
            color=self._coordinator.text_color(),
            effect=self._coordinator.effect,
            speed=self._coordinator.speed,
            dwell=self._coordinator.dwell,
        )
