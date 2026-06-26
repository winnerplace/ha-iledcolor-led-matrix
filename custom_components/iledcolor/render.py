from __future__ import annotations

import functools
import io
import pathlib
import threading
from collections.abc import Sequence

try:
    import freetype as _freetype
except Exception:  # pragma: no cover - optional, falls back to monochrome
    _freetype = None

_ft_lock = threading.Lock()

RGB = tuple[int, int, int]
Grid = list[list[RGB]]

_BUNDLED_FONT = pathlib.Path(__file__).resolve().parent / "fonts" / "Pretendard-Regular.otf"
_EMOJI_FONT = pathlib.Path(__file__).resolve().parent / "fonts" / "NotoEmoji-Regular.ttf"
_ZERO_WIDTH = frozenset({0x200D, 0xFE0E, 0xFE0F})


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

    if _BUNDLED_FONT.exists():
        return str(_BUNDLED_FONT)
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


_FONTS_DIR = pathlib.Path(__file__).resolve().parent / "fonts"
_FONT_FILES = {
    "pretendard": _BUNDLED_FONT,
    "unifont": _FONTS_DIR / "Unifont-Regular.otf",
    "d2coding": _FONTS_DIR / "D2Coding-Regular.ttf",
    "galmuri14": _FONTS_DIR / "Galmuri14.ttf",
    "cafe24ssurround": _FONTS_DIR / "Cafe24Ssurround.ttf",
    "cafe24ssurroundair": _FONTS_DIR / "Cafe24SsurroundAir.ttf",
    "mona12": _FONTS_DIR / "Mona12.ttf",
}


def font_file(name: str | None) -> str | None:
    path = _FONT_FILES.get(name or "")
    if path and path.exists():
        return str(path)
    return _default_font_path()


@functools.lru_cache(maxsize=64)
def _load_font(path: str | None, size: int):
    from PIL import ImageFont

    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _is_emoji(ch: str) -> bool:
    o = ord(ch)
    return (
        0x1F000 <= o <= 0x1FAFF
        or 0x2600 <= o <= 0x27BF
        or 0x2B00 <= o <= 0x2BFF
        or 0x1F1E6 <= o <= 0x1F1FF
        or o in (0x203C, 0x2049, 0x2122, 0x2139, 0x2194, 0x2328, 0x23CF, 0x24C2, 0x25AA, 0x25FE)
    )


@functools.lru_cache(maxsize=16)
def _emoji_font(size: int):
    from PIL import ImageFont

    if not _EMOJI_FONT.exists():
        return None
    try:
        return ImageFont.truetype(str(_EMOJI_FONT), size)
    except OSError:
        return None


def _font_for(ch: str, size: int, primary: str | None):
    if _is_emoji(ch):
        emoji = _emoji_font(size)
        if emoji is not None:
            return emoji
    return _load_font(primary, size)


@functools.lru_cache(maxsize=16)
def _ft_face(path: str | None):
    if _freetype is None or not path:
        return None
    try:
        return _freetype.Face(path)
    except Exception:
        return None


def _ft_color_glyph(path: str | None, ch: str, px: int):
    face = _ft_face(path)
    if face is None:
        return None
    from PIL import Image

    with _ft_lock:
        try:
            if face.get_char_index(ord(ch)) == 0:
                return None
            face.set_pixel_sizes(0, max(1, px))
            face.load_char(ch, _freetype.FT_LOAD_RENDER | _freetype.FT_LOAD_COLOR)
        except Exception:
            return None
        bm = face.glyph.bitmap
        w, rows, pitch, mode = bm.width, bm.rows, bm.pitch, bm.pixel_mode
        if rows == 0 or w == 0 or mode != 7:  # 7 = FT_PIXEL_MODE_BGRA (color)
            return None
        buf = bytes(bm.buffer)
    if pitch != w * 4:
        packed = bytearray()
        for y in range(rows):
            packed += buf[y * pitch : y * pitch + w * 4]
        buf = bytes(packed)
    return Image.frombytes("RGBA", (w, rows), buf, "raw", "BGRA").convert("RGB")


def _color_emoji_image(primary: str | None, ch: str, px: int):
    mona = _FONT_FILES.get("mona12")
    candidates = [primary]
    if mona is not None and mona.exists():
        candidates.append(str(mona))
    seen: set[str] = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        glyph = _ft_color_glyph(path, ch, px)
        if glyph is not None:
            return glyph
    return None


def _draw_run(image, fonts, chars, widths, x, y, text_h, height, color, primary, size, weight):
    from PIL import Image, ImageDraw

    draw = ImageDraw.Draw(image)
    for font, ch, w in zip(fonts, chars, widths):
        if _is_emoji(ch):
            glyph = _color_emoji_image(primary, ch, size)
            if glyph is not None:
                gw, gh = max(1, round(w)), max(1, text_h)
                image.paste(
                    glyph.resize((gw, gh), Image.LANCZOS),
                    (round(x), round((height - text_h) / 2)),
                )
                x += w
                continue
        if weight > 0:
            draw.text((x, y), ch, fill=color, font=font, stroke_width=weight, stroke_fill=color)
        else:
            draw.text((x, y), ch, fill=color, font=font)
        x += w


def rasterize_text(
    text: str,
    width: int,
    height: int,
    *,
    color: RGB = (255, 255, 255),
    bg: RGB = (0, 0, 0),
    font_path: str | None = None,
    weight: int = 0,
    slide: bool = False,
) -> Grid:
    from PIL import Image

    chars = [c for c in text if ord(c) not in _ZERO_WIDTH]
    if not chars:
        return _to_grid(Image.new("RGB", (width, height), bg), width, height)

    primary = font_path or _default_font_path()
    pad = 2 * max(0, weight)

    def layout(size: int):
        fonts = [_font_for(c, size, primary) for c in chars]
        widths = [f.getlength(c) for f, c in zip(fonts, chars)]
        boxes = [f.getbbox(c) for f, c in zip(fonts, chars)]
        top = min(b[1] for b in boxes)
        bottom = max(b[3] for b in boxes)
        return fonts, widths, sum(widths), top, bottom - top

    if slide:
        size = 6
        fonts, widths, total, top, text_h = layout(size)
        for candidate in range(height, 5, -1):
            fonts, widths, total, top, text_h = layout(candidate)
            if text_h + pad <= height:
                size = candidate
                break
        canvas_w = max(width, int(round(total)) + pad)
        image = Image.new("RGB", (canvas_w, height), bg)
        x = (canvas_w - total) / 2 if canvas_w <= width else pad / 2
        y = (height - text_h) / 2 - top
        _draw_run(image, fonts, chars, widths, x, y, text_h, height, color, primary, size, weight)
        return _to_grid(image, canvas_w, height)

    size = 6
    fonts, widths, total, top, text_h = layout(size)
    for candidate in range(height, 5, -1):
        fonts, widths, total, top, text_h = layout(candidate)
        if total + pad <= width and text_h + pad <= height:
            size = candidate
            break
    image = Image.new("RGB", (width, height), bg)
    x = (width - total) / 2
    y = (height - text_h) / 2 - top
    _draw_run(image, fonts, chars, widths, x, y, text_h, height, color, primary, size, weight)
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
