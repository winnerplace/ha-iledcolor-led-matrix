from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_INTERVAL, DOMAIN, INTERVAL_MAX, INTERVAL_MIN, INTERVAL_STEP
from .device import IledColorDevice
from .status_display import StatusDisplay


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([IledColorIntervalNumber(entry, runtime["device"], runtime["coordinator"])])


class IledColorIntervalNumber(NumberEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "update_interval"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = INTERVAL_MIN
    _attr_native_max_value = INTERVAL_MAX
    _attr_native_step = INTERVAL_STEP
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, entry: ConfigEntry, device: IledColorDevice, coordinator: StatusDisplay) -> None:
        self._coordinator = coordinator
        base = entry.unique_id or entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{base}_interval"
        self._attr_device_info = device.device_info(base)

    @property
    def native_value(self) -> float:
        return float(self._coordinator.interval)

    async def async_set_native_value(self, value: float) -> None:
        await self._coordinator.async_set(**{CONF_INTERVAL: int(value)})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.add_listener(self.async_write_ha_state))
