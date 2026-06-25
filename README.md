# iLEDcolor LED Matrix — Home Assistant integration

Local BLE control of LED matrix signs that ship with the **iLEDcolor** app
(`com.led.iledcolor`, Shenzhen I-ledshow, Jieli SoC) — no cloud, no phone app.

Reverse-engineered from the vendor's published source
(`gitee.com/led-show/ileddemo`) and the shipped APK. Protocol details:
`.claude/docs/analysis/iledcolor-ble-protocol-spec.md`.

[![Open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=winnerplace&repository=ha-iledcolor-led-matrix&category=integration)

> **Status: 26.6.5 — validation build.** 26.6.5 fixes the advertisement parse
> off-by-one (panels were read as e.g. `24579x4096`; now correct), keeps the legacy
> power/brightness framing as default, and adds integration **options** to override
> panel size / color type / frame generation when auto-detection is wrong.
>
> Power and brightness (legacy framing) are the high-confidence path. Text / image /
> GIF use the reverse-engineered 0xA8 bulk format
> (`.claude/docs/analysis/iledcolor-bulk-wire-spec.md`); the disassembly shows 0xA8
> is unconditional (no legacy chunk path), but the pixel-block byte alignment is
> **still unverified on hardware** — treat `display_*` and the Status display as
> experimental until confirmed with a capture.

Versioning: CalVer `YY.M.BUILD` (no zero-padding; build number starts at 1).

## Requirements

- Home Assistant with the **Bluetooth** integration working (HAOS with a built-in
  or USB Bluetooth adapter, or an ESPHome Bluetooth proxy in range).
- The device powered on and **disconnected from the phone app** (these devices
  usually allow a single BLE connection).

## Install via HACS

One click — [![Open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=winnerplace&repository=ha-iledcolor-led-matrix&category=integration) — then install and restart.

Or manually:

1. HACS → ⋮ → **Custom repositories** → add this repo's GitHub URL, category
   **Integration**.
2. Install **iLEDcolor LED Matrix**, then restart Home Assistant.
3. Add the integration:
   [![Start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=iledcolor)
   — or Settings → Devices & Services → **Add Integration** → *iLEDcolor*, or
   accept the auto-discovered device. Pick your matrix from the list.

## What works

- `light` entity: on/off (`0x0A`) and brightness (`0x09`, mapped 1–10).
- `iledcolor.send_raw` service: write arbitrary bytes to `write1` (A951) or
  `write2` (A952) for protocol experimentation. Notifications from the device are
  logged at debug level.

Experimental (bulk path, unverified on hardware):

- `iledcolor.display_text` — rasterize text and send it as pixels.
- `iledcolor.display_image` / `iledcolor.display_gif` — fit a local file or URL to
  the panel and send it.
- **Status display**: a `number` (update interval, 30–600 s slider) + `switch`
  pair, plus an options flow to pick sensor entities, that rotates their values
  onto the panel via `display_text`.

Enable debug logging to watch the wire:

```yaml
logger:
  default: info
  logs:
    custom_components.iledcolor: debug
```

## Validating opcodes

The fastest single-frame commands are high-confidence; verify them and report
back what the screen does and what `A953` notifies:

```yaml
# Developer Tools → Actions → iledcolor.send_raw
data: "54 09 00 04 05 00 00 66"   # brightness level 5 (legacy 2-byte)
characteristic: write1
```

## Notes

- Repo: https://github.com/winnerplace/ha-iledcolor-led-matrix
- Not affiliated with the manufacturer. iDotMatrix integrations are **not**
  compatible (different GATT service and framing).
