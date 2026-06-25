from __future__ import annotations

import colorsys
import logging
import random
from collections.abc import Callable
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    COLOR_DEFAULT,
    CONF_COLOR,
    CONF_COLOR_ON,
    CONF_COLOR_RANDOM,
    CONF_DWELL,
    CONF_EFFECT,
    CONF_ENABLED,
    CONF_ENTITIES,
    CONF_INTERVAL,
    CONF_MTU,
    CONF_SPEED,
    DEFAULT_DWELL,
    DEFAULT_EFFECT,
    DEFAULT_INTERVAL,
    DEFAULT_SPEED,
)
from .device import IledColorDevice

RGB = tuple[int, int, int]


def _random_color() -> RGB:
    r, g, b = colorsys.hsv_to_rgb(random.random(), 1.0, 1.0)
    return (round(r * 255), round(g * 255), round(b * 255))

_LOGGER = logging.getLogger(__name__)

_INVALID = {"unavailable", "unknown", "none", ""}


class StatusDisplay:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device: IledColorDevice) -> None:
        self.hass = hass
        self.entry = entry
        self.device = device
        self.interval = DEFAULT_INTERVAL
        self.enabled = False
        self.entities: list[str] = []
        self.effect = DEFAULT_EFFECT
        self.speed = DEFAULT_SPEED
        self.dwell = DEFAULT_DWELL
        self.mtu = 0
        self.color: RGB = COLOR_DEFAULT
        self.color_on = False
        self.color_random = False
        self._index = 0
        self._unsub: Callable[[], None] | None = None
        self._listeners: list[Callable[[], None]] = []
        self._warned = False
        self.apply_options()

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    @callback
    def notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    def apply_options(self) -> None:
        opts = self.entry.options
        self.interval = int(opts.get(CONF_INTERVAL, DEFAULT_INTERVAL))
        self.enabled = bool(opts.get(CONF_ENABLED, False))
        self.entities = list(opts.get(CONF_ENTITIES, []))
        self.effect = int(opts.get(CONF_EFFECT, DEFAULT_EFFECT))
        self.speed = int(opts.get(CONF_SPEED, DEFAULT_SPEED))
        self.dwell = int(opts.get(CONF_DWELL, DEFAULT_DWELL))
        self.mtu = int(opts.get(CONF_MTU, 0))
        self.color = tuple(opts.get(CONF_COLOR, COLOR_DEFAULT))  # type: ignore[assignment]
        self.color_on = bool(opts.get(CONF_COLOR_ON, False))
        self.color_random = bool(opts.get(CONF_COLOR_RANDOM, False))
        if self.enabled and not self.entities:
            _LOGGER.warning(
                "Status display is on but no entities are selected; pick them in the "
                "integration options (Settings > Devices & Services > iLEDcolor > Configure)"
            )
        self._reschedule()

    async def async_set(self, **changes) -> None:
        opts = {**self.entry.options, **changes}
        self.hass.config_entries.async_update_entry(self.entry, options=opts)

    @callback
    def _reschedule(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        if self.enabled and self.entities and self.interval > 0:
            self._unsub = async_track_time_interval(
                self.hass, self._tick, timedelta(seconds=self.interval)
            )
            self.hass.async_create_task(self._tick())

    def _rows(self) -> list[str]:
        rows: list[str] = []
        for entity_id in self.entities:
            state = self.hass.states.get(entity_id)
            if state is None or str(state.state).lower() in _INVALID:
                continue
            name = state.attributes.get("friendly_name", entity_id)
            name = self._strip_device(entity_id, name)
            unit = state.attributes.get("unit_of_measurement", "")
            area = self._area_name(entity_id)
            parts = [p for p in (area, name, f"{state.state}{unit}") if p]
            rows.append(" ".join(parts))
        return rows

    def _strip_device(self, entity_id: str, name: str) -> str:
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is None or entry.device_id is None:
            return name
        device = dr.async_get(self.hass).async_get(entry.device_id)
        if device is None:
            return name
        dev_name = device.name_by_user or device.name
        if dev_name and name.startswith(f"{dev_name} "):
            return name[len(dev_name) + 1 :]
        return name

    def _area_name(self, entity_id: str) -> str:
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is None:
            return ""
        area_id = entry.area_id
        if area_id is None and entry.device_id:
            device = dr.async_get(self.hass).async_get(entry.device_id)
            area_id = device.area_id if device else None
        if area_id is None:
            return ""
        area = ar.async_get(self.hass).async_get_area(area_id)
        return area.name if area else ""

    def text_color(self) -> RGB:
        if self.color_random:
            return _random_color()
        return self.color if self.color_on else COLOR_DEFAULT

    def colors_for(self, count: int) -> list[RGB]:
        if self.color_random:
            return [_random_color() for _ in range(count)]
        return [self.color if self.color_on else COLOR_DEFAULT] * count

    async def _tick(self, _now: datetime | None = None) -> None:
        rows = self._rows()
        if not rows:
            return
        try:
            await self.device.display_status(
                rows,
                colors=self.colors_for(len(rows)),
                effect=self.effect,
                speed=self.speed,
                dwell=self.dwell,
            )
            self._warned = False
        except Exception as err:  # noqa: BLE001
            if not self._warned:
                self._warned = True
                _LOGGER.warning("%s status display send failed: %s", self.device.address, err)

    async def async_stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
