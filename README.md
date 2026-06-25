# iLEDcolor LED Matrix — Home Assistant integration

Local BLE control of LED matrix signs that ship with the **iLEDcolor** app
(`com.led.iledcolor`, Shenzhen I-ledshow, Jieli SoC) — no cloud, no phone app.

Reverse-engineered from the vendor's published source
(`gitee.com/led-show/ileddemo`) and the shipped APK. Protocol details:
`.claude/docs/analysis/iledcolor-ble-protocol-spec.md`.

[![Open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=winnerplace&repository=ha-iledcolor-led-matrix&category=integration)

> **Status: 26.6.2 — validation build.** Power and brightness only. The frames
> are derived statically; confirm against your device before relying on it. Text /
> image / GIF (bulk transfer) are not implemented yet — the bulk wire format (0xA8)
> is now reverse-engineered (`.claude/docs/analysis/iledcolor-bulk-wire-spec.md`)
> but unverified on hardware.
>
> 26.6.2 corrects the brightness frame to the shipped app's encoding
> (`11 − level`, 18-byte payload) — **this is the change to validate**. An auto
> "Status display" (number + switch entities to rotate sensor values) is scaffolded
> but does not render to the panel yet (pending the bulk path).

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
data: "54 09 00 14 06 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 77"  # brightness level 5
characteristic: write1
```

## Notes

- Repo: https://github.com/winnerplace/ha-iledcolor-led-matrix
- Not affiliated with the manufacturer. iDotMatrix integrations are **not**
  compatible (different GATT service and framing).
