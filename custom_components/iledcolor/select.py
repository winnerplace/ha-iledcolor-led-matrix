from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_EFFECT, DOMAIN, EFFECT_OPTIONS
from .device import IledColorDevice
from .status_display import StatusDisplay


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([IledColorEffectSelect(entry, runtime["device"], runtime["coordinator"])])


class IledColorEffectSelect(SelectEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "effect"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = EFFECT_OPTIONS

    def __init__(
        self, entry: ConfigEntry, device: IledColorDevice, coordinator: StatusDisplay
    ) -> None:
        self._coordinator = coordinator
        base = entry.unique_id or entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{base}_effect"
        self._attr_device_info = device.device_info(base)

    @property
    def current_option(self) -> str:
        index = self._coordinator.effect
        if 0 <= index < len(EFFECT_OPTIONS):
            return EFFECT_OPTIONS[index]
        return EFFECT_OPTIONS[0]

    async def async_select_option(self, option: str) -> None:
        await self._coordinator.async_set(**{CONF_EFFECT: EFFECT_OPTIONS.index(option)})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.add_listener(self.async_write_ha_state))
