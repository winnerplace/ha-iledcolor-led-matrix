from __future__ import annotations

import io
from collections.abc import Sequence

RGB = tuple[int, int, int]
Grid = list[list[RGB]]


def _to_grid(image, width: int, height: int) -> Grid:
    rgb = image.convert("RGB")
    px = rgb.load()
    return [[px[x, y] for x in range(width)] for y in range(height)]


def _fit(image, width: int, height: int, fit: str, bg: RGB):
    from PIL import Image

    if fit == "stretch":
        return image.resize((width, height))

    src_w, src_h = image.size
    if fit == "cover":
        scale = max(width / src_w, height / src_h)
    else:  # contain
        scale = min(width / src_w, height / src_h)
    new = image.resize((max(1, round(src_w * scale)), max(1, round(src_h * scale))))
    canvas = Image.new("RGB", (width, height), bg)
    off = ((width - new.width) // 2, (height - new.height) // 2)
    canvas.paste(new, off)
    return canvas


def _pick_font(text: str, width: int, height: int, font_path: str | None):
    from PIL import ImageFont

    for size in range(height, 5, -1):
        font = (
            ImageFont.truetype(font_path, size)
            if font_path
            else ImageFont.load_default(size=size)
        )
        box = font.getbbox(text)
        if (box[2] - box[0]) <= width and (box[3] - box[1]) <= height:
            return font
    return ImageFont.load_default(size=6)


def rasterize_text(
    text: str,
    width: int,
    height: int,
    *,
    color: RGB = (255, 255, 255),
    bg: RGB = (0, 0, 0),
    font_path: str | None = None,
) -> Grid:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)
    font = _pick_font(text, width, height, font_path)
    box = font.getbbox(text)
    tx = (width - (box[2] - box[0])) // 2 - box[0]
    ty = (height - (box[3] - box[1])) // 2 - box[1]
    draw.text((tx, ty), text, fill=color, font=font)
    return _to_grid(image, width, height)


def load_image(
    source: str | bytes,
    width: int,
    height: int,
    *,
    fit: str = "contain",
    bg: RGB = (0, 0, 0),
) -> Grid:
    from PIL import Image

    handle = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    with Image.open(handle) as image:
        return _to_grid(_fit(image.convert("RGB"), width, height, fit, bg), width, height)


def load_gif(
    source: str | bytes,
    width: int,
    height: int,
    *,
    fit: str = "contain",
    bg: RGB = (0, 0, 0),
) -> tuple[list[Grid], list[int]]:
    from PIL import Image, ImageSequence

    handle = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    frames: list[Grid] = []
    delays: list[int] = []
    with Image.open(handle) as image:
        for frame in ImageSequence.Iterator(image):
            delays.append(int(frame.info.get("duration", 100)))
            frames.append(_to_grid(_fit(frame.convert("RGB"), width, height, fit, bg), width, height))
    return frames, delays


def read_gif_bytes(source: str | bytes) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    with open(source, "rb") as handle:
        return handle.read()


def is_gif(data: Sequence[int]) -> bool:
    return bytes(data[:4]) == bytes([0x47, 0x49, 0x46, 0x38])
