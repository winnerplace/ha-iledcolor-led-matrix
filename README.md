# iLEDcolor LED Matrix — Home Assistant integration

Local BLE control of LED matrix signs that ship with the **iLEDcolor** app
(`com.led.iledcolor`, Shenzhen I-ledshow, Jieli SoC) — no cloud, no phone app.

Reverse-engineered from the vendor's published source
(`gitee.com/led-show/ileddemo`) and the shipped APK. Protocol details:
`.claude/docs/analysis/iledcolor-ble-protocol-spec.md`.

> **Status: 26.6.1 — validation build.** Power and brightness only. The frames
> are derived statically; confirm against your device before relying on it. Text /
> image / GIF (bulk transfer) are not implemented yet.

Versioning: CalVer `YY.M.BUILD` (no zero-padding; build number starts at 1).

## Requirements

- Home Assistant with the **Bluetooth** integration working (HAOS with a built-in
  or USB Bluetooth adapter, or an ESPHome Bluetooth proxy in range).
- The device powered on and **disconnected from the phone app** (these devices
  usually allow a single BLE connection).

## Install via HACS

1. HACS → ⋮ → **Custom repositories** → add this repo's GitHub URL, category
   **Integration**.
2. Install **iLEDcolor LED Matrix**, then restart Home Assistant.
3. Settings → Devices & Services → **Add Integration** → *iLEDcolor*, or accept
   the auto-discovered device. Pick your matrix from the list.

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
data: "54 09 00 04 05 00 00 66"   # brightness level 5
characteristic: write1
```

## Notes

- Edit `manifest.json` `codeowners` / `documentation` / `issue_tracker` and the
  HACS repo URL before publishing.
- Not affiliated with the manufacturer. iDotMatrix integrations are **not**
  compatible (different GATT service and framing).
