from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    COLOR_TYPE_DEFAULT,
    COLOR_TYPE_OPTIONS,
    CONF_COLOR_TYPE,
    CONF_EFFECT,
    CONF_FONT,
    CONF_GENERATION,
    CONF_MODE,
    DOMAIN,
    EFFECT_OPTIONS,
    FONT_DEFAULT,
    FONT_OPTIONS,
    GEN_DEFAULT,
    GEN_OPTIONS,
    MODE_DEFAULT,
    MODE_OPTIONS,
)
from .device import IledColorDevice
from .status_display import StatusDisplay


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    device, coord = runtime["device"], runtime["coordinator"]
    async_add_entities(
        [
            IledColorModeSelect(entry, device, coord),
            IledColorEffectSelect(entry, device, coord),
            IledColorOptionSelect(
                entry, device, coord, "font", CONF_FONT, FONT_OPTIONS, FONT_DEFAULT
            ),
            IledColorOptionSelect(
                entry, device, coord, "color_type", CONF_COLOR_TYPE, COLOR_TYPE_OPTIONS, COLOR_TYPE_DEFAULT
            ),
            IledColorOptionSelect(
                entry, device, coord, "generation", CONF_GENERATION, GEN_OPTIONS, GEN_DEFAULT
            ),
        ]
    )


class IledColorModeSelect(SelectEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "display_mode"
    _attr_options = MODE_OPTIONS

    def __init__(
        self, entry: ConfigEntry, device: IledColorDevice, coordinator: StatusDisplay
    ) -> None:
        self._coordinator = coordinator
        base = entry.unique_id or entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{base}_display_mode"
        self._attr_device_info = device.device_info(base)

    @property
    def current_option(self) -> str:
        return self._coordinator.mode if self._coordinator.mode in MODE_OPTIONS else MODE_DEFAULT

    async def async_select_option(self, option: str) -> None:
        await self._coordinator.async_set(**{CONF_MODE: option})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.add_listener(self.async_write_ha_state))


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


class IledColorOptionSelect(SelectEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        entry: ConfigEntry,
        device: IledColorDevice,
        coordinator: StatusDisplay,
        key: str,
        conf_key: str,
        options: list[str],
        default: str,
    ) -> None:
        self._entry = entry
        self._coordinator = coordinator
        self._conf_key = conf_key
        self._default = default
        self._attr_translation_key = key
        self._attr_options = options
        base = entry.unique_id or entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{base}_{key}"
        self._attr_device_info = device.device_info(base)

    @property
    def current_option(self) -> str:
        value = self._entry.options.get(self._conf_key, self._default)
        return value if value in self._attr_options else self._default

    async def async_select_option(self, option: str) -> None:
        await self._coordinator.async_set(**{self._conf_key: option})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.add_listener(self.async_write_ha_state))
