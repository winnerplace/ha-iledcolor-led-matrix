from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo

from . import bulk, render
from .const import (
    CHAR_NOTIFY,
    CHAR_WRITE1,
    CHAR_WRITE2,
    CONF_COLOR_TYPE,
    CONF_FLIP_H,
    CONF_FLIP_V,
    CONF_FONT,
    CONF_GENERATION,
    CONF_HEIGHT,
    CONF_MTU,
    CONF_WEIGHT,
    CONF_WIDTH,
    DOMAIN,
    GEN_APP2024,
    GEN_LEGACY,
)
from .protocol import Capability, brightness_frame, build_frame, power_frame

_LOGGER = logging.getLogger(__name__)

_DEFAULT_MTU = 23
_ACK_TIMEOUT = 0.8
_ACK_GIVE_UP = 3
_WINDOW = 32
_GIF_STAY = 10
_MAX_PANEL = 1024
RGB = tuple[int, int, int]


def gif_speed(delays_ms: list[int]) -> int:
    if not delays_ms:
        return 1
    total = sum(min(round(d / 10), 4) * 10 for d in delays_ms)
    return max(1, min(80, int(total / len(delays_ms) / 20.0)))


class IledColorDevice:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, capability: Capability) -> None:
        self.hass = hass
        self.entry = entry
        self.address = entry.data[CONF_ADDRESS]
        self.capability = capability
        self.last_notify: bytes | None = None
        self.power_on = False
        self._client: BleakClientWithServiceCache | None = None
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[bytes], None]] = []
        self._power_listeners: list[Callable[[], None]] = []
        self._ack = asyncio.Event()
        self._acks = 0

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    def _eff_size(self) -> tuple[int, int]:
        opts = self.entry.options
        return (
            int(opts.get(CONF_WIDTH) or self.capability.width or 0),
            int(opts.get(CONF_HEIGHT) or self.capability.height or 0),
        )

    def _color_type(self) -> int:
        override = self.entry.options.get(CONF_COLOR_TYPE, "auto")
        if override == "mono":
            return 1
        if override == "full":
            return 3
        return self.capability.color_type or 3

    def _app2024(self) -> bool:
        return self.entry.options.get(CONF_GENERATION, GEN_LEGACY) == GEN_APP2024

    def _panel(self) -> tuple[int, int]:
        w, h = self._eff_size()
        if not (1 <= w <= _MAX_PANEL and 1 <= h <= _MAX_PANEL):
            raise RuntimeError(
                f"implausible panel size {w}x{h}; set it in the integration options"
            )
        return w, h

    def add_notify_listener(self, cb: Callable[[bytes], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    def add_power_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._power_listeners.append(cb)
        return lambda: self._power_listeners.remove(cb)

    @callback
    def _emit_power(self) -> None:
        for cb in list(self._power_listeners):
            cb()

    @callback
    def _on_notify(self, _char, data: bytearray) -> None:
        self.last_notify = bytes(data)
        _LOGGER.debug("%s notify <- %s", self.address, self.last_notify.hex())
        if data:
            self._acks += 1
            self._ack.set()
        for cb in list(self._listeners):
            cb(self.last_notify)

    @callback
    def _on_disconnect(self, _client) -> None:
        _LOGGER.info("%s disconnected", self.address)
        self._client = None

    async def _ensure(self) -> None:
        if self.connected:
            return
        ble_device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
        if ble_device is None:
            raise RuntimeError(f"{self.address} not in range")
        t0 = time.monotonic()
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
        mtu = getattr(self._client, "mtu_size", 0)
        _LOGGER.info("%s connected in %.2fs (mtu=%s)", self.address, time.monotonic() - t0, mtu)
        if mtu and mtu <= 23:
            _LOGGER.warning(
                "%s negotiated MTU is only %s — transfers are split into ~1-byte chunks and "
                "will be very slow. If you use an ESPHome Bluetooth proxy, update it; or set "
                "Color type to 'mono' in the integration options.",
                self.address,
                mtu,
            )

    async def _write(self, char: str, data: bytes) -> None:
        async with self._lock:
            await self._ensure()
            assert self._client is not None
            _LOGGER.debug("%s write %s -> %s", self.address, char[4:8], data.hex())
            await self._client.write_gatt_char(char, data, response=False)

    async def send(self, op: int, payload: list[int], char: str = CHAR_WRITE1) -> None:
        await self._write(char, build_frame(op, payload))

    async def send_raw(self, data: bytes, char: str = CHAR_WRITE1) -> None:
        _LOGGER.info("%s send_raw %s -> %s", self.address, char[4:8], bytes(data).hex())
        await self._write(char, bytes(data))

    async def set_power(self, on: bool) -> None:
        _LOGGER.info("%s power %s", self.address, "on" if on else "off")
        await self._write(CHAR_WRITE1, power_frame(on, app2024=self._app2024()))
        self.power_on = on
        self._emit_power()

    async def set_brightness_level(self, level: int) -> None:
        _LOGGER.info("%s brightness %d", self.address, level)
        await self._write(CHAR_WRITE1, brightness_frame(level, app2024=self._app2024()))

    async def _stream(self, chunks: list[bytes], char: str) -> None:
        assert self._client is not None
        self._acks = 0
        throttle = True
        misses = 0
        for index, chunk in enumerate(chunks):
            while throttle and index - self._acks >= _WINDOW:
                self._ack.clear()
                try:
                    await asyncio.wait_for(self._ack.wait(), timeout=_ACK_TIMEOUT)
                    misses = 0
                except asyncio.TimeoutError:
                    misses += 1
                    if misses >= _ACK_GIVE_UP:
                        throttle = False
                        _LOGGER.debug("%s no chunk ACK; streaming remainder", self.address)
            await self._client.write_gatt_char(char, chunk, response=False)

    async def _send_source(
        self,
        width: int,
        height: int,
        frames: list[bytes],
        *,
        effects: int = 0,
        speed: int = 0,
        gif: bool = False,
        stay: int = _GIF_STAY,
    ) -> None:
        async with self._lock:
            await self._ensure()
            assert self._client is not None
            if not self.power_on:
                await self._client.write_gatt_char(
                    CHAR_WRITE1, power_frame(True, app2024=self._app2024()), response=False
                )
                self.power_on = True
                self._emit_power()
            mtu = (
                int(self.entry.options.get(CONF_MTU) or 0)
                or getattr(self._client, "mtu_size", 0)
                or _DEFAULT_MTU
            )
            t0 = time.monotonic()
            if self._app2024():
                item = bulk.item_data(0, 0, width, height, frames, effect=effects, speed=speed)
                chunks = bulk.bulk_frames(bulk.program_frame([item]), mtu)
                await self._stream(chunks, CHAR_WRITE2)
                _LOGGER.info(
                    "%s sent app2024 (%d frames, %d chunks, mtu=%d) in %.2fs",
                    self.address, len(frames), len(chunks), mtu, time.monotonic() - t0,
                )
                return
            if gif:
                text_data = bulk.legacy_gif_source(
                    width, height, frames, speed=speed, stay=stay, effects=effects
                )
            else:
                params = bulk.graffiti_program_params(
                    width, height, frame_count=len(frames), effects=effects, speed=speed, dwell=stay
                )
                text_data = bulk.legacy_source(params, b"".join(frames))
            header = bulk.legacy_header_frame(text_data)
            chunks = bulk.legacy_bulk_frames(text_data, mtu)
            await self._client.write_gatt_char(CHAR_WRITE1, header, response=False)
            await self._stream(chunks, CHAR_WRITE2)
            _LOGGER.info(
                "%s sent legacy (%d frames, %dB, %d chunks, mtu=%d) in %.2fs",
                self.address, len(frames), len(text_data), len(chunks), mtu, time.monotonic() - t0,
            )

    def _encode(self, grid, w: int, h: int) -> bytes:
        opts = self.entry.options
        if opts.get(CONF_FLIP_H):
            grid = [list(reversed(row)) for row in grid]
        if opts.get(CONF_FLIP_V):
            grid = list(reversed(grid))
        return bulk.encode_frame(grid, w, h, self._color_type())

    def _font_path(self) -> str | None:
        return render.font_file(self.entry.options.get(CONF_FONT))

    def _weight(self) -> int:
        return int(self.entry.options.get(CONF_WEIGHT, 0))

    def _raster_text(self, text: str, w: int, h: int, color: RGB) -> bytes:
        grid = render.rasterize_text(
            text, w, h, color=color, font_path=self._font_path(), weight=self._weight()
        )
        return self._encode(grid, w, h)

    def _raster_fill(self, color: RGB, w: int, h: int) -> bytes:
        return self._encode([[color for _ in range(w)] for _ in range(h)], w, h)

    def _raster_texts(
        self, texts: list[str], w: int, h: int, color: RGB, colors: list[RGB] | None = None
    ) -> list[bytes]:
        font = self._font_path()
        weight = self._weight()
        return [
            self._encode(
                render.rasterize_text(
                    t, w, h, color=(colors[i] if colors else color), font_path=font, weight=weight
                ),
                w,
                h,
            )
            for i, t in enumerate(texts)
        ]

    def _raster_image(
        self, source: str | bytes, w: int, h: int, fit: str, chroma: RGB | None, tol: int
    ) -> bytes:
        return self._encode(render.load_image(source, w, h, fit=fit, chroma=chroma, tol=tol), w, h)

    def _raster_gif(
        self,
        source: str | bytes,
        w: int,
        h: int,
        fit: str,
        chroma: RGB | None,
        tol: int,
        max_frames: int | None,
    ) -> tuple[list[bytes], int]:
        grids, delays = render.load_gif(
            source, w, h, fit=fit, chroma=chroma, tol=tol, max_frames=max_frames
        )
        frames = [self._encode(g, w, h) for g in grids]
        return frames, gif_speed(delays)

    async def display_text(
        self,
        text: str,
        *,
        color: RGB = (255, 255, 255),
        effect: int = 0,
        speed: int = 1,
        dwell: int = 30,
    ) -> None:
        w, h = self._panel()
        pixels = await self.hass.async_add_executor_job(self._raster_text, text, w, h, color)
        await self._send_source(w, h, [pixels], effects=effect, speed=speed, stay=dwell)

    async def display_status(
        self,
        rows: list[str],
        *,
        color: RGB = (255, 255, 255),
        colors: list[RGB] | None = None,
        effect: int = 0,
        speed: int = 1,
        dwell: int = 30,
    ) -> None:
        if not rows:
            return
        w, h = self._panel()
        frames = await self.hass.async_add_executor_job(
            self._raster_texts, rows, w, h, color, colors
        )
        await self._send_source(
            w, h, frames, effects=effect, speed=speed, gif=len(frames) > 1, stay=dwell
        )

    async def display_color(
        self, color: RGB, *, effect: int = 0, speed: int = 1, dwell: int = 30
    ) -> None:
        w, h = self._panel()
        pixels = await self.hass.async_add_executor_job(self._raster_fill, color, w, h)
        await self._send_source(w, h, [pixels], effects=effect, speed=speed, stay=dwell)

    async def display_image(
        self,
        source: str | bytes,
        *,
        fit: str = "contain",
        chroma: RGB | None = None,
        tol: int = 0,
        effect: int = 0,
        speed: int = 1,
        dwell: int = 30,
    ) -> None:
        w, h = self._panel()
        pixels = await self.hass.async_add_executor_job(
            self._raster_image, source, w, h, fit, chroma, tol
        )
        await self._send_source(w, h, [pixels], effects=effect, speed=speed, stay=dwell)

    async def display_gif(
        self,
        source: str | bytes,
        *,
        fit: str = "contain",
        chroma: RGB | None = None,
        tol: int = 0,
        max_frames: int | None = None,
        stay: int = _GIF_STAY,
        effect: int = 0,
        speed: int | None = None,
    ) -> None:
        w, h = self._panel()
        frames, auto_speed = await self.hass.async_add_executor_job(
            self._raster_gif, source, w, h, fit, chroma, tol, max_frames
        )
        await self._send_source(
            w, h, frames, effects=effect, speed=speed if speed is not None else auto_speed,
            gif=True, stay=stay,
        )

    def device_info(self, unique_id: str) -> DeviceInfo:
        w, h = self._eff_size()
        return DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, self.address)},
            identifiers={(DOMAIN, unique_id)},
            manufacturer="I-ledshow",
            model=f"{w}x{h}" if w else "LED Matrix",
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
