import importlib.util
import io
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "iledcolor"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"iledcolor_{name}", _ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


render = _load("render")
bulk = _load("bulk")

try:
    from PIL import Image
    _HAVE_PIL = True
except ImportError:
    _HAVE_PIL = False


def _png(width, height, color):
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_rasterize_text_grid_shape():
    if not _HAVE_PIL:
        return
    grid = render.rasterize_text("HI", 64, 16, color=(255, 0, 0))
    assert len(grid) == 16
    assert all(len(row) == 64 for row in grid)
    assert any(px != (0, 0, 0) for row in grid for px in row)


def test_load_image_fit_stretch():
    if not _HAVE_PIL:
        return
    grid = render.load_image(_png(8, 8, (0, 128, 255)), 32, 16, fit="stretch")
    assert len(grid) == 16 and len(grid[0]) == 32
    assert grid[0][0] == (0, 128, 255)


def test_image_grid_feeds_encoder():
    if not _HAVE_PIL:
        return
    grid = render.load_image(_png(4, 4, (10, 20, 30)), 4, 4, fit="stretch")
    out = bulk.encode_full_color(grid, 4, 4)
    assert out == bytes([10, 20, 30]) * 16


def test_is_gif_magic():
    assert render.is_gif(b"GIF89a....")
    assert not render.is_gif(b"\x89PNG")


def _mona():
    return render.font_file("mona12")


def test_slide_widens_long_text():
    if not _HAVE_PIL:
        return
    grid = render.rasterize_text("가나다라마바사아자차카타파하", 96, 16, font_path=_mona(), slide=True)
    assert len(grid) == 16
    assert len(grid[0]) > 96  # rendered wider than the panel for scrolling


def test_slide_short_text_stays_panel_width():
    if not _HAVE_PIL:
        return
    grid = render.rasterize_text("짧음", 96, 16, font_path=_mona(), slide=True)
    assert len(grid[0]) == 96


def test_slide_text_height_controls_size():
    if not _HAVE_PIL:
        return
    text = "가나다라마바사아자차카타파하거너더러"
    small = render.rasterize_text(text, 96, 16, font_path=_mona(), slide=True, text_height=8)
    big = render.rasterize_text(text, 96, 16, font_path=_mona(), slide=True, text_height=16)
    assert len(small[0]) < len(big[0])  # smaller font height -> narrower glyphs


def test_non_slide_stays_panel_width():
    if not _HAVE_PIL:
        return
    grid = render.rasterize_text("가나다라마바사아자차카타파하", 96, 16, font_path=_mona())
    assert len(grid[0]) == 96


def _chroma(grid):
    return any(
        abs(r - g) > 30 or abs(g - b) > 30 or abs(r - b) > 30
        for row in grid for r, g, b in row
    )


def test_color_emoji_when_freetype_available():
    if not _HAVE_PIL or render._freetype is None:
        return
    grid = render.rasterize_text("🍎", 96, 16, font_path=_mona())
    assert _chroma(grid)  # color emoji rasterized, not monochrome


def test_plain_text_is_monochrome():
    if not _HAVE_PIL:
        return
    grid = render.rasterize_text("안녕", 96, 16, color=(255, 255, 255), font_path=_mona())
    assert not _chroma(grid)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} passed (PIL={_HAVE_PIL})")
