from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback

from .const import CHAR_NOTIFY, CHAR_WRITE1
from .protocol import Capability, brightness_frame, build_frame, power_frame

_LOGGER = logging.getLogger(__name__)


class IledColorDevice:
    def __init__(self, hass: HomeAssistant, address: str, capability: Capability) -> None:
        self.hass = hass
        self.address = address
        self.capability = capability
        self.last_notify: bytes | None = None
        self._client: BleakClientWithServiceCache | None = None
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[bytes], None]] = []

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    def add_notify_listener(self, cb: Callable[[bytes], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    @callback
    def _on_notify(self, _char, data: bytearray) -> None:
        self.last_notify = bytes(data)
        _LOGGER.debug("%s notify <- %s", self.address, self.last_notify.hex())
        for cb in list(self._listeners):
            cb(self.last_notify)

    @callback
    def _on_disconnect(self, _client) -> None:
        _LOGGER.debug("%s disconnected", self.address)

    async def _ensure(self) -> None:
        if self.connected:
            return
        ble_device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
        if ble_device is None:
            raise RuntimeError(f"{self.address} not in range")
        self._client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            self.address,
            disconnected_callback=self._on_disconnect,
        )
        try:
            assert self._client is not None
            await self._client.start_notify(CHAR_NOTIFY, self._on_notify)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("%s notify subscribe failed: %s", self.address, err)

    async def _write(self, char: str, data: bytes) -> None:
        async with self._lock:
            await self._ensure()
            assert self._client is not None
            _LOGGER.debug("%s write %s -> %s", self.address, char[4:8], data.hex())
            await self._client.write_gatt_char(char, data, response=False)

    async def send(self, op: int, payload: list[int], char: str = CHAR_WRITE1) -> None:
        await self._write(char, build_frame(op, payload))

    async def send_raw(self, data: bytes, char: str = CHAR_WRITE1) -> None:
        await self._write(char, bytes(data))

    async def set_power(self, on: bool) -> None:
        await self._write(CHAR_WRITE1, power_frame(on))

    async def set_brightness_level(self, level: int) -> None:
        await self._write(CHAR_WRITE1, brightness_frame(level))

    async def disconnect(self) -> None:
        async with self._lock:
            if self._client is not None:
                try:
                    await self._client.disconnect()
                except Exception:  # noqa: BLE001
                    pass
                self._client = None
