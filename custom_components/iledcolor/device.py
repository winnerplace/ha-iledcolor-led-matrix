from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo

from . import bulk, render
from .const import CHAR_NOTIFY, CHAR_WRITE1, CHAR_WRITE2, DOMAIN
from .protocol import Capability, brightness_frame, build_frame, power_frame

_LOGGER = logging.getLogger(__name__)

_DEFAULT_MTU = 23
_ACK_TIMEOUT = 2.0
RGB = tuple[int, int, int]


def gif_speed(delays_ms: list[int]) -> int:
    if not delays_ms:
        return 1
    total = sum(min(round(d / 10), 4) * 10 for d in delays_ms)
    return max(1, min(80, int(total / len(delays_ms) / 20.0)))


class IledColorDevice:
    def __init__(self, hass: HomeAssistant, address: str, capability: Capability) -> None:
        self.hass = hass
        self.address = address
        self.capability = capability
        self.last_notify: bytes | None = None
        self._client: BleakClientWithServiceCache | None = None
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[bytes], None]] = []
        self._ack = asyncio.Event()

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
        if data and data[0] == bulk.BULK_MARKER:
            self._ack.set()
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

    def _panel(self) -> tuple[int, int]:
        w, h = self.capability.width, self.capability.height
        if not w or not h:
            raise RuntimeError(
                "panel size unknown; re-add the device so its advertisement is parsed"
            )
        return w, h

    async def _send_resource(self, items: list[bytes]) -> None:
        frame = bulk.program_frame(items)
        async with self._lock:
            await self._ensure()
            assert self._client is not None
            mtu = getattr(self._client, "mtu_size", 0) or _DEFAULT_MTU
            chunks = bulk.bulk_frames(frame, mtu)
            _LOGGER.debug(
                "%s bulk send: %d bytes, %d chunks, mtu=%d",
                self.address,
                len(frame),
                len(chunks),
                mtu,
            )
            for chunk in chunks:
                self._ack.clear()
                await self._client.write_gatt_char(CHAR_WRITE2, chunk, response=False)
                try:
                    await asyncio.wait_for(self._ack.wait(), timeout=_ACK_TIMEOUT)
                except asyncio.TimeoutError:
                    _LOGGER.debug("%s bulk ack timeout, continuing", self.address)

    async def display_text(
        self, text: str, *, color: RGB = (255, 255, 255), effect: int = 0, speed: int = 50
    ) -> None:
        width, height = self._panel()
        grid = render.rasterize_text(text, width, height, color=color)
        frame = bulk.encode_frame(grid, width, height, self.capability.color_type or 3)
        item = bulk.item_data(0, 0, width, height, [frame], effect=effect, speed=speed)
        await self._send_resource([item])

    async def display_image(self, source: str | bytes, *, fit: str = "contain") -> None:
        width, height = self._panel()
        grid = render.load_image(source, width, height, fit=fit)
        frame = bulk.encode_frame(grid, width, height, self.capability.color_type or 3)
        item = bulk.item_data(0, 0, width, height, [frame])
        await self._send_resource([item])

    async def display_gif(self, source: str | bytes, *, fit: str = "contain") -> None:
        width, height = self._panel()
        color_type = self.capability.color_type or 3
        if self.capability.supports_gif:
            raw = render.read_gif_bytes(source)
            item = bulk.item_data(
                0, 0, width, height, [raw], type_byte=bulk.ITEM_TYPE_GIF, speed=4
            )
        else:
            frames, delays = render.load_gif(source, width, height, fit=fit)
            speed = gif_speed(delays)
            blocks = [
                bulk.gif_frame_block(speed, bulk.encode_frame(f, width, height, color_type))
                for f in frames
            ]
            item = bulk.item_data(0, 0, width, height, blocks, speed=max(speed, 10))
        await self._send_resource([item])

    def device_info(self, unique_id: str) -> DeviceInfo:
        cap = self.capability
        return DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, self.address)},
            identifiers={(DOMAIN, unique_id)},
            manufacturer="I-ledshow",
            model=f"{cap.width}x{cap.height}" if cap.width else "LED Matrix",
            name="iLEDcolor",
        )

    async def disconnect(self) -> None:
        async with self._lock:
            if self._client is not None:
                try:
                    await self._client.disconnect()
                except Exception:  # noqa: BLE001
                    pass
                self._client = None
