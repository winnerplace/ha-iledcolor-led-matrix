from __future__ import annotations

from dataclasses import dataclass

from .bulk import simple_frame as build_frame
from .const import DEVICE_MARKER, OP_BRIGHTNESS, OP_POWER

__all__ = ["build_frame", "power_frame", "brightness_frame", "Capability",
           "find_capability_blob", "parse_capability"]


def power_frame(on: bool, app2024: bool = False) -> bytes:
    pad = 17 if app2024 else 9
    return build_frame(OP_POWER, [1 if on else 0] + [0] * pad)


def brightness_frame(level: int, app2024: bool = False) -> bytes:
    level = max(1, min(10, level))
    if app2024:
        return build_frame(OP_BRIGHTNESS, [11 - level] + [0] * 17)
    return build_frame(OP_BRIGHTNESS, [10 - level, 0])


@dataclass
class Capability:
    width: int = 0
    height: int = 0
    color_type: int = 0
    version_code: int = 0
    customer_id: int = 0
    fun_code: int = 0
    screen_type_id: int = 0

    @property
    def is_full_color(self) -> bool:
        return self.color_type == 3

    @property
    def supports_brightness(self) -> bool:
        return self.version_code >= 6

    @property
    def supports_time(self) -> bool:
        return bool(self.fun_code & 0x01)

    @property
    def supports_gif(self) -> bool:
        return bool(self.fun_code & 0x04)

    def as_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "color_type": self.color_type,
            "version_code": self.version_code,
            "customer_id": self.customer_id,
            "fun_code": self.fun_code,
            "screen_type_id": self.screen_type_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Capability":
        return cls(**{k: data.get(k, 0) for k in cls.__dataclass_fields__})


def _u16(b: bytes, i: int) -> int:
    return int.from_bytes(b[i : i + 2], "big")


def find_capability_blob(service_info) -> bytes | None:
    for cid, data in (service_info.manufacturer_data or {}).items():
        full = cid.to_bytes(2, "little") + bytes(data)
        if DEVICE_MARKER in full:
            idx = full.index(DEVICE_MARKER)
            return full[idx:]
        if DEVICE_MARKER in bytes(data):
            idx = bytes(data).index(DEVICE_MARKER)
            return bytes(data)[idx:]
    for data in (service_info.service_data or {}).values():
        if DEVICE_MARKER in bytes(data):
            idx = bytes(data).index(DEVICE_MARKER)
            return bytes(data)[idx:]
    return None


def parse_capability(blob: bytes | None) -> Capability | None:
    if not blob or len(blob) < 16:
        return None
    return Capability(
        screen_type_id=int.from_bytes(blob[0:4], "big"),
        height=_u16(blob, 4),
        width=_u16(blob, 6),
        color_type=blob[8],
        version_code=_u16(blob, 9),
        customer_id=_u16(blob, 11),
        fun_code=_u16(blob, 14),
    )
