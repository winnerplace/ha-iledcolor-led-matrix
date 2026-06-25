from __future__ import annotations

from collections.abc import Sequence

BULK_MARKER = 0xA8
BULK_SUB_DATA = 0x00
_BULK_END_BODY = bytes([0xA8, 0x02, 0x00, 0x06, 0x02])
_CHUNK_OVERHEAD = 13

FRAME_HEADER = 0x54
OP_PROGRAM = 0x06

ITEM_TYPE_IMAGE = 2
ITEM_TYPE_GIF = 6
ITEM_FIELD23_DEFAULT = 0x32

MONO_MASK = (0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01)

Pixel = Sequence[int]
Grid = Sequence[Sequence[Pixel]]


def _be16(value: int) -> bytes:
    return (value & 0xFFFF).to_bytes(2, "big")


def simple_frame(op: int, payload: Sequence[int] | bytes) -> bytes:
    payload = bytes(payload)
    body = bytes([FRAME_HEADER, op]) + _be16(len(payload) + 2) + payload
    return body + _checksum(body)


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


def legacy_bulk_frames(payload: bytes, mtu: int) -> list[bytes]:
    size = max(1, mtu - 32)  # demo: mtu -= 20; chunkSize = mtu - 12
    frames = [
        simple_frame(BULK_SUB_DATA, idx.to_bytes(4, "big") + _be16(len(payload[off : off + size])) + payload[off : off + size])
        for idx, off in enumerate(range(0, len(payload), size))
    ]
    frames.append(simple_frame(0x01, [0x01]))
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
            if round(_gray(pixels[y][x])) >= avg:
                cur |= MONO_MASK[n % 8]
            n += 1
            if n % 8 == 0:
                out.append(cur)
                cur = 0
    if n % 8:
        out.append(cur)
    return bytes(out)


def encode_frame(pixels: Grid, width: int, height: int, color_type: int, lut: Sequence[int] | None = None) -> bytes:
    if color_type in (0, 1):
        return encode_mono(pixels, width, height)
    return encode_full_color(pixels, width, height, lut)


def gif_frame_block(speed: int, pixel_bytes: bytes) -> bytes:
    return _be16(speed) + pixel_bytes


def item_data(
    x: int,
    y: int,
    width: int,
    height: int,
    frame_blocks: Sequence[bytes],
    *,
    type_byte: int = ITEM_TYPE_IMAGE,
    effect: int = 0,
    sub_effect: int = 0,
    speed: int = ITEM_FIELD23_DEFAULT,
    frame_type: int = 0,
    extra: int = 0,
    reserved: bytes = bytes(6),
    trailing: bytes = b"",
) -> bytes:
    out = bytearray()
    out += _be16(x) + _be16(y) + _be16(width) + _be16(height)
    out += reserved
    out += bytes([type_byte])
    out += _be16(len(frame_blocks))
    out += bytes([effect & 0xFF, sub_effect & 0xFF, speed & 0xFF, frame_type & 0xFF, extra & 0xFF])
    out += bytes(3)
    for block in frame_blocks:
        out += block
    out += trailing
    return bytes(out)


def program_resource(items: Sequence[bytes]) -> bytes:
    body = bytearray([len(items), 0, 0, 0])
    for item in items:
        body += len(item).to_bytes(4, "big") + item
    return crc32c(bytes(body)).to_bytes(4, "big") + bytes(body)


def program_frame(items: Sequence[bytes]) -> bytes:
    return simple_frame(OP_PROGRAM, program_resource(items))


def graffiti_program_params(
    width: int,
    height: int,
    *,
    source_type: int = 0,
    frame_count: int = 1,
    effects: int = 0,
    speed: int = 0,
    dwell: int = 30,
    frame_type: int = 0,
    brightness: int = 100,
) -> bytes:
    dwell = max(dwell, 30) if effects == 0 else dwell
    return (
        bytes([0, 0, 0, 0])
        + _be16(width)
        + _be16(height)
        + bytes([0, 0, 0])
        + bytes([source_type & 0xFF])
        + _be16(frame_count)
        + bytes([effects & 0xFF, speed & 0xFF, dwell & 0xFF, frame_type & 0xFF, brightness & 0xFF])
        + bytes([0, 0, 0])
    )


def legacy_source(params: bytes, pixel_data: bytes) -> bytes:
    data = bytes([1, 0, 0, 0]) + bytes(16) + params + pixel_data
    return crc32c(data).to_bytes(4, "big") + data


def legacy_header_frame(text_data: bytes) -> bytes:
    payload = text_data[:4] + len(text_data).to_bytes(4, "big") + bytes([0, 0, 0])
    return simple_frame(OP_PROGRAM, payload)


def legacy_gif_params(
    width: int,
    height: int,
    frame_count: int,
    *,
    speed: int,
    stay: int,
    effects: int = 0,
    source_type: int = 0,
    brightness: int = 100,
) -> bytes:
    return (
        bytes([0, 0, 0, 0])
        + _be16(width)
        + _be16(height)
        + bytes([0, 0, 0])
        + bytes([source_type & 0xFF])
        + _be16(frame_count)
        + bytes([effects & 0xFF, speed & 0xFF, stay & 0xFF, 0, brightness & 0xFF])
        + bytes([0, 0, 0])
    )


def legacy_gif_source(
    width: int,
    height: int,
    frames: Sequence[bytes],
    *,
    speed: int,
    stay: int,
    effects: int = 0,
    brightness: int = 100,
) -> bytes:
    params = legacy_gif_params(
        width, height, len(frames), speed=speed, stay=stay, effects=effects, brightness=brightness
    )
    pixel_data = b"".join(frames) + int(speed).to_bytes(2, "big")
    return legacy_source(params, pixel_data)
