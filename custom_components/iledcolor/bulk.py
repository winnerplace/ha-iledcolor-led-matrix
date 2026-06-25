from __future__ import annotations

from collections.abc import Sequence

BULK_MARKER = 0xA8
BULK_SUB_DATA = 0x00
_BULK_END_BODY = bytes([0xA8, 0x02, 0x00, 0x06, 0x02])
_CHUNK_OVERHEAD = 13

MONO_MASK = (0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01)

Pixel = Sequence[int]
Grid = Sequence[Sequence[Pixel]]


def _be16(value: int) -> bytes:
    return (value & 0xFFFF).to_bytes(2, "big")


def _checksum(body: bytes) -> bytes:
    return _be16(sum(body))


def bulk_data_frame(index: int, chunk: bytes) -> bytes:
    inner = len(chunk)
    body = (
        bytes([BULK_MARKER, BULK_SUB_DATA])
        + _be16(inner + 2)
        + index.to_bytes(4, "big")
        + _be16(inner)
        + chunk
    )
    return body + _checksum(body)


def bulk_end_frame() -> bytes:
    return _BULK_END_BODY + _checksum(_BULK_END_BODY)


def bulk_frames(payload: bytes, mtu: int) -> list[bytes]:
    size = max(1, mtu - _CHUNK_OVERHEAD)
    frames = [
        bulk_data_frame(idx, payload[off : off + size])
        for idx, off in enumerate(range(0, len(payload), size))
    ]
    frames.append(bulk_end_frame())
    return frames


def crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 & -(crc & 1))
    return crc ^ 0xFFFFFFFF


def _gray(pixel: Pixel) -> float:
    r, g, b = pixel[0], pixel[1], pixel[2]
    return 0.299 * b + 0.587 * g + 0.114 * r


def encode_full_color(pixels: Grid, width: int, height: int, lut: Sequence[int] | None = None) -> bytes:
    out = bytearray()
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[y][x][0], pixels[y][x][1], pixels[y][x][2]
            if lut is not None:
                r, g, b = lut[r], lut[g], lut[b]
            out += bytes((r, g, b))
    return bytes(out)


def _avg_gray(pixels: Grid, width: int, height: int) -> float:
    total = sum(round(_gray(pixels[y][x])) for y in range(height) for x in range(width))
    return total / (width * height)


def encode_mono(pixels: Grid, width: int, height: int) -> bytes:
    avg = _avg_gray(pixels, width, height)
    out = bytearray()
    cur = 0
    n = 0
    for x in range(width):
        for y in range(height):
            if round(_gray(pixels[y][x])) < avg:
                cur |= MONO_MASK[n % 8]
            n += 1
            if n % 8 == 0:
                out.append(cur)
                cur = 0
    if n % 8:
        out.append(cur)
    return bytes(out)
