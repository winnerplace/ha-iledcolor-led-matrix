import importlib.util
import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "iledcolor"


def _load_pkg():
    pkg = types.ModuleType("iledcolor")
    pkg.__path__ = [str(_ROOT)]
    sys.modules["iledcolor"] = pkg
    mods = {}
    for name in ("const", "bulk", "protocol"):
        spec = importlib.util.spec_from_file_location(f"iledcolor.{name}", _ROOT / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"iledcolor.{name}"] = mod
        spec.loader.exec_module(mod)
        mods[name] = mod
    return mods


_mods = _load_pkg()
protocol = _mods["protocol"]
bulk = _mods["bulk"]


def test_parse_capability_offsets_96x16():
    # marker 'TBD' is the first bytes of screenType; real 96x16 full-color panel
    blob = bytes([0x54, 0x42, 0x44, 0x01,  # screen_type [0:4]
                  0x00, 0x10,              # height [4:6] = 16
                  0x00, 0x60,              # width  [6:8] = 96
                  0x03,                    # color_type [8] = full
                  0x00, 0x06,              # version [9:11] = 6
                  0x00, 0x00,              # customer [11:13]
                  0x00,                    # gap [13]
                  0x00, 0x04])             # fun_code [14:16]
    cap = protocol.parse_capability(blob)
    assert cap is not None
    assert cap.height == 16
    assert cap.width == 96
    assert cap.color_type == 3
    assert cap.version_code == 6
    assert cap.is_full_color
    assert cap.supports_brightness  # version >= 6
    assert cap.supports_gif  # fun_code & 0x04


def test_parse_capability_too_short():
    assert protocol.parse_capability(bytes(15)) is None
    assert protocol.parse_capability(None) is None


def test_power_frame_legacy_vs_app2024():
    assert protocol.power_frame(True) == bulk.simple_frame(0x0A, [1] + [0] * 9)
    assert protocol.power_frame(False) == bulk.simple_frame(0x0A, [0] + [0] * 9)
    assert protocol.power_frame(True, app2024=True) == bulk.simple_frame(0x0A, [1] + [0] * 17)


def test_brightness_frame_legacy_vs_app2024():
    assert protocol.brightness_frame(5) == bulk.simple_frame(0x09, [10 - 5, 0])
    assert protocol.brightness_frame(5, app2024=True) == bulk.simple_frame(0x09, [11 - 5] + [0] * 17)
    # clamp
    assert protocol.brightness_frame(0) == bulk.simple_frame(0x09, [10 - 1, 0])
    assert protocol.brightness_frame(99) == bulk.simple_frame(0x09, [10 - 10, 0])


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} passed")
