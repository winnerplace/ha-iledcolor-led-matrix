from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import COLOR_DEFAULT, CONF_COLOR, CONF_COLOR_ON, DOMAIN
from .device import IledColorDevice
from .status_display import StatusDisplay


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    device, coord = runtime["device"], runtime["coordinator"]
    async_add_entities(
        [
            IledColorLight(entry, device, coord),
            IledColorTextColorLight(entry, device, coord),
        ]
    )


class IledColorLight(LightEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(
        self, entry: ConfigEntry, device: IledColorDevice, coordinator: StatusDisplay
    ) -> None:
        self._device = device
        self._coordinator = coordinator
        self._attr_unique_id = entry.unique_id or entry.data[CONF_ADDRESS]
        self._attr_brightness = 255
        self._attr_device_info = device.device_info(self._attr_unique_id)

    @property
    def is_on(self) -> bool:
        return self._device.power_on

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self._device.power_on = last.state == "on"
            if (brightness := last.attributes.get(ATTR_BRIGHTNESS)) is not None:
                self._attr_brightness = int(brightness)
        self.async_on_remove(self._device.add_power_listener(self.async_write_ha_state))
        if self._device.power_on:
            self.hass.async_create_task(self._coordinator.async_refresh())

    async def async_turn_on(self, **kwargs: Any) -> None:
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            await self._device.set_brightness_level(max(1, round(brightness / 255 * 10)))
            self._attr_brightness = brightness
        await self._device.set_power(True)
        await self._coordinator.async_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._device.set_power(False)


class IledColorTextColorLight(LightEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "text_color"
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_color_mode = ColorMode.RGB

    def __init__(
        self, entry: ConfigEntry, device: IledColorDevice, coordinator: StatusDisplay
    ) -> None:
        self._entry = entry
        self._coordinator = coordinator
        base = entry.unique_id or entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{base}_text_color"
        self._attr_device_info = device.device_info(base)

    @property
    def is_on(self) -> bool:
        return bool(self._entry.options.get(CONF_COLOR_ON, False))

    @property
    def brightness(self) -> int:
        return 255

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        return tuple(self._entry.options.get(CONF_COLOR, COLOR_DEFAULT))  # type: ignore[return-value]

    async def async_turn_on(self, **kwargs: Any) -> None:
        changes: dict[str, Any] = {CONF_COLOR_ON: True}
        if (rgb := kwargs.get(ATTR_RGB_COLOR)) is not None:
            changes[CONF_COLOR] = list(rgb)
        await self._coordinator.async_set(**changes)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._coordinator.async_set(**{CONF_COLOR_ON: False})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.add_listener(self.async_write_ha_state))
