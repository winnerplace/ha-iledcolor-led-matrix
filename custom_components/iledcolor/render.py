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


def _flatten(image, bg: RGB):
    from PIL import Image

    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        canvas = Image.new("RGBA", rgba.size, (bg[0], bg[1], bg[2], 255))
        canvas.alpha_composite(rgba)
        return canvas.convert("RGB")
    return image.convert("RGB")


def _key_out(image, chroma: RGB | None, tol: int, bg: RGB):
    if chroma is None:
        return image
    rgb = image.convert("RGB")
    px = rgb.load()
    cr, cg, cb = chroma
    for y in range(rgb.height):
        for x in range(rgb.width):
            r, g, b = px[x, y]
            if abs(r - cr) <= tol and abs(g - cg) <= tol and abs(b - cb) <= tol:
                px[x, y] = bg
    return rgb


_FONT_CANDIDATES = (
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
)


def _default_font_path() -> str | None:
    import os

    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def _pick_font(text: str, width: int, height: int, font_path: str | None):
    from PIL import ImageFont

    path = font_path or _default_font_path()

    def _at(size: int):
        if path:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
        return ImageFont.load_default(size=size)

    for size in range(height, 5, -1):
        font = _at(size)
        box = font.getbbox(text)
        if (box[2] - box[0]) <= width and (box[3] - box[1]) <= height:
            return font
    return _at(6)


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
    chroma: RGB | None = None,
    tol: int = 0,
) -> Grid:
    from PIL import Image

    handle = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    with Image.open(handle) as image:
        flat = _key_out(_flatten(image, bg), chroma, tol, bg)
        return _to_grid(_fit(flat, width, height, fit, bg), width, height)


def _decimate(frames: list[Grid], delays: list[int], max_frames: int | None):
    if not max_frames or len(frames) <= max_frames:
        return frames, delays
    n = len(frames)
    idx = sorted({min(n - 1, round(i * n / max_frames)) for i in range(max_frames)})
    return [frames[j] for j in idx], [delays[j] for j in idx]


def load_gif(
    source: str | bytes,
    width: int,
    height: int,
    *,
    fit: str = "contain",
    bg: RGB = (0, 0, 0),
    chroma: RGB | None = None,
    tol: int = 0,
    max_frames: int | None = None,
) -> tuple[list[Grid], list[int]]:
    from PIL import Image, ImageSequence

    handle = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    frames: list[Grid] = []
    delays: list[int] = []
    with Image.open(handle) as image:
        for frame in ImageSequence.Iterator(image):
            delays.append(int(frame.info.get("duration", 100)))
            flat = _key_out(_flatten(frame, bg), chroma, tol, bg)
            frames.append(_to_grid(_fit(flat, width, height, fit, bg), width, height))
    return _decimate(frames, delays, max_frames)


def read_gif_bytes(source: str | bytes) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    with open(source, "rb") as handle:
        return handle.read()


def is_gif(data: Sequence[int]) -> bool:
    return bytes(data[:4]) == bytes([0x47, 0x49, 0x46, 0x38])
