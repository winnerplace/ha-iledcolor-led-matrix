import importlib.util
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "iledcolor"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"iledcolor_{name}", _ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


const = _load("const")


def test_merged_rows_prefers_rows_key():
    opts = {
        const.CONF_ROWS: ["sensor.a", "💗", "sensor.b"],
        const.CONF_ENTITIES: ["sensor.old"],
        const.CONF_CUSTOM_TEXTS: ["old text"],
    }
    assert const.merged_rows(opts) == ["sensor.a", "💗", "sensor.b"]


def test_merged_rows_migrates_legacy_keys():
    opts = {
        const.CONF_ENTITIES: ["sensor.a", "sensor.b"],
        const.CONF_CUSTOM_TEXTS: [" 💗 ", "", "hello"],
    }
    assert const.merged_rows(opts) == ["sensor.a", "sensor.b", "💗", "hello"]


def test_merged_rows_empty_options():
    assert const.merged_rows({}) == []


def test_merged_rows_strips_blank_rows():
    opts = {const.CONF_ROWS: ["sensor.a", "  ", ""]}
    assert const.merged_rows(opts) == ["sensor.a"]
