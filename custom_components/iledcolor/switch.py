from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENABLED, DOMAIN
from .device import IledColorDevice
from .status_display import StatusDisplay


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([IledColorStatusSwitch(entry, runtime["device"], runtime["coordinator"])])


class IledColorStatusSwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "status_display"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, device: IledColorDevice, coordinator: StatusDisplay) -> None:
        self._coordinator = coordinator
        base = entry.unique_id or entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{base}_status_display"
        self._attr_device_info = device.device_info(base)

    @property
    def is_on(self) -> bool:
        return self._coordinator.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._coordinator.async_set(**{CONF_ENABLED: True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._coordinator.async_set(**{CONF_ENABLED: False})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.add_listener(self.async_write_ha_state))
