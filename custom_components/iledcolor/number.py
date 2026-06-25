from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DWELL,
    CONF_INTERVAL,
    CONF_MTU,
    CONF_SPEED,
    DOMAIN,
    DWELL_MAX,
    DWELL_MIN,
    INTERVAL_MAX,
    INTERVAL_MIN,
    INTERVAL_STEP,
    MTU_MAX,
    SPEED_MAX,
    SPEED_MIN,
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
            IledColorIntervalNumber(entry, device, coord),
            IledColorSettingNumber(entry, device, coord, "speed", CONF_SPEED, SPEED_MIN, SPEED_MAX),
            IledColorSettingNumber(entry, device, coord, "dwell", CONF_DWELL, DWELL_MIN, DWELL_MAX),
            IledColorSettingNumber(entry, device, coord, "mtu", CONF_MTU, 0, MTU_MAX),
        ]
    )


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


class IledColorSettingNumber(NumberEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        entry: ConfigEntry,
        device: IledColorDevice,
        coordinator: StatusDisplay,
        key: str,
        conf_key: str,
        minimum: int,
        maximum: int,
    ) -> None:
        self._coordinator = coordinator
        self._key = key
        self._conf_key = conf_key
        self._attr_translation_key = key
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = 1
        base = entry.unique_id or entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{base}_{key}"
        self._attr_device_info = device.device_info(base)

    @property
    def native_value(self) -> float:
        return float(getattr(self._coordinator, self._key))

    async def async_set_native_value(self, value: float) -> None:
        await self._coordinator.async_set(**{self._conf_key: int(value)})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.add_listener(self.async_write_ha_state))
