from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
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
    async_add_entities([IledColorLight(entry, device)])


class IledColorLight(LightEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(self, entry: ConfigEntry, device: IledColorDevice) -> None:
        self._device = device
        self._attr_unique_id = entry.unique_id or entry.data[CONF_ADDRESS]
        self._attr_is_on = False
        self._attr_brightness = 255
        self._attr_device_info = device.device_info(self._attr_unique_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            await self._device.set_brightness_level(max(1, round(brightness / 255 * 10)))
            self._attr_brightness = brightness
        await self._device.set_power(True)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._device.set_power(False)
        self._attr_is_on = False
        self.async_write_ha_state()
