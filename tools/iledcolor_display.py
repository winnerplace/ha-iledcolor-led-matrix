#!/usr/bin/env python3
"""iLEDcolor 직접 디스플레이 테스트 (Mac ↔ 기기, HA 우회).

목적: legacy 벌크 전송을 bleak로 직접 보내며 속도/ACK 전략 실험.
의존성: pip install bleak pillow

선행: HA가 기기 BLE를 점유 중이면 충돌. HA 통합을 비활성화하거나 기기를 HA 범위 밖으로.

예시:
  python iledcolor_display.py scan
  python iledcolor_display.py text  "Hi" --w 96 --h 16 --mode ackwait
  python iledcolor_display.py fill  --w 96 --h 16 --rgb 255,0,0 --mode response
  python iledcolor_display.py status "실외 온도 24.5°C" "거실 습도 60%" --w 96 --h 16
  python iledcolor_display.py status "온도 24.5" --repeat 3 --interval 30   # 2회차부터 기기 unchanged(3) 응답 확인
  python iledcolor_display.py status "온도 24.5" --repeat 3 --vary          # 매회 내용 변경 → 정상 재전송
  python iledcolor_display.py monitor
모드: ackwait(청크마다 notify 1개 대기) / nowait(무대기 연속) / response(write-with-response)

status = HA 상태표시(상태 롤링) 재현: 줄마다 프레임 1장, 멀티프레임 순환 재생.
헤더 전송 후 기기 응답(54 06)을 해석해 3(내용 동일)이면 본문을 생략한다 — 26.7.3 동작 미러.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import pathlib
import sys
import time
import types

from bleak import BleakClient, BleakScanner

SERVICE = "0000a950-0000-1000-8000-00805f9b34fb"
WRITE1 = "0000a951-0000-1000-8000-00805f9b34fb"
WRITE2 = "0000a952-0000-1000-8000-00805f9b34fb"
NOTIFY = "0000a953-0000-1000-8000-00805f9b34fb"
NAME_HINT = "iledcolor"

_CC = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "iledcolor"


def _load_pkg():
    pkg = types.ModuleType("il")
    pkg.__path__ = [str(_CC)]
    sys.modules["il"] = pkg
    mods = {}
    for name in ("const", "bulk", "protocol", "render"):
        spec = importlib.util.spec_from_file_location(f"il.{name}", _CC / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"il.{name}"] = mod
        spec.loader.exec_module(mod)
        mods[name] = mod
    return mods


_mods = _load_pkg()
bulk = _mods["bulk"]
render = _mods["render"]
protocol = _mods["protocol"]


async def _find(target: str | None):
    devs = await BleakScanner.discover(timeout=6.0)
    for d in devs:
        name = (d.name or "").lower()
        if target:
            if target.lower() in (d.address.lower(), name):
                return d
        elif NAME_HINT in name:
            return d
    return None


def _gif_speed(delays_ms: list[int]) -> int:
    if not delays_ms:
        return 1
    total = sum(min(round(d / 10), 4) * 10 for d in delays_ms)
    return max(1, min(80, int(total / len(delays_ms) / 20.0)))


def _reorder(grids, order):
    if order == "rgb":
        return grids
    idx = {"r": 0, "g": 1, "b": 2}
    p = [idx[c] for c in order]
    return [[[(px[p[0]], px[p[1]], px[p[2]]) for px in row] for row in g] for g in grids]


def _resolve_font(args):
    font_path = getattr(args, "font_path", None)
    if font_path:
        return font_path
    name = getattr(args, "font", None)
    if not name:
        return None
    if pathlib.Path(name).exists():
        return name
    return render.font_file(name)


def _status_colors(args, count):
    raw = getattr(args, "rowcolors", None)
    if not raw:
        return [args.rgb] * count
    colors = [_rgb(part) for part in raw.split(";")]
    return [colors[i % len(colors)] for i in range(count)]


def _build_grids(args):
    w, h = args.w, args.h
    speed = 50
    raw_pixel = None
    if args.cmd == "text":
        grids = [
            render.rasterize_text(
                args.text, w, h, color=args.rgb, font_path=_resolve_font(args),
                antialias=getattr(args, "antialias", False),
            )
        ]
    elif args.cmd == "status":
        font = _resolve_font(args)
        antialias = getattr(args, "antialias", False)
        colors = _status_colors(args, len(args.rows))
        grids = [
            render.rasterize_text(row, w, h, color=colors[i], font_path=font, antialias=antialias)
            for i, row in enumerate(args.rows)
        ]
        speed = 1
    elif args.cmd == "fill":
        grids = [[[args.rgb for _ in range(w)] for _ in range(h)]]
    elif args.cmd == "image":
        grids = [render.load_image(args.path, w, h, fit=args.fit, chroma=args.chroma, tol=args.tol)]
    else:  # gif
        grids, delays = render.load_gif(
            args.path, w, h, fit=args.fit, chroma=args.chroma, tol=args.tol, max_frames=args.maxframes
        )
        speed = _gif_speed(delays)
        if args.gifmode == "raw":
            raw_pixel = render.read_gif_bytes(args.path)
    if args.speed is not None:
        speed = args.speed
    return _reorder(grids, args.order), speed, raw_pixel


def _build_source(args) -> bytes:
    w, h = args.w, args.h
    grids, speed, raw_pixel = _build_grids(args)

    if raw_pixel is not None:
        frame_count = len(grids)
        pixel = raw_pixel
        source_type = 6
    else:
        frames = [bulk.encode_frame(g, w, h, 3) for g in grids]
        frame_count = len(frames)
        pixel = b"".join(frames)
        source_type = 0
        if args.cmd == "gif" or (args.cmd == "status" and frame_count > 1):
            pixel += speed.to_bytes(2, "big")

    if args.srctype is not None:
        source_type = args.srctype
    if args.dwell is not None:
        stay = args.dwell
    elif args.cmd == "gif":
        stay = 10
    else:
        stay = 30

    be16 = lambda v: int(v).to_bytes(2, "big")
    params = (
        bytes(4)
        + be16(w)
        + be16(h)
        + bytes([0, 0, 0])
        + bytes([source_type & 0xFF])
        + be16(frame_count)
        + bytes([args.effects & 0xFF, speed & 0xFF, stay & 0xFF, 0, 100])
        + bytes([0, 0, 0])
    )
    print(
        f"frames={frame_count} speed={speed} stay={stay} srctype={source_type} "
        f"effects={args.effects} gifmode={args.gifmode} pixel={len(pixel)}B"
    )
    return bulk.legacy_source(params, pixel)


_PROGRAM_STATUS_LABEL = {
    1: "ok",
    2: "no space",
    3: "unchanged",
}


async def _send_once(client, args, acks, ack_event, text_data):
    mtu = getattr(client, "mtu_size", 0) or 23
    header = bulk.legacy_header_frame(text_data)
    chunks = bulk.legacy_bulk_frames(text_data, mtu)
    print(f"mtu={mtu} textData={len(text_data)}B chunks={len(chunks)} mode={args.mode}")

    acks.update({"data": 0, "end": None, "program": None, "error": None})
    t0 = time.monotonic()
    await client.write_gatt_char(WRITE1, header, response=False)

    try:
        while acks["program"] is None:
            ack_event.clear()
            await asyncio.wait_for(ack_event.wait(), timeout=1.0)
    except asyncio.TimeoutError:
        pass
    status = acks["program"]
    if status is not None:
        print(f"  header resp 54 06 status={status} ({_PROGRAM_STATUS_LABEL.get(status, '?')})")
    else:
        print("  header resp: none (1s) — proceeding")
    if status == 3 and not args.force:
        print(f"  DEDUPE: device already has this content; bulk skipped ({time.monotonic() - t0:.2f}s)")
        return
    if status == 2:
        print("  ABORT: device storage full")
        return

    aborted = False
    if args.mode == "ackwait":
        for i, ch in enumerate(chunks):
            ack_event.clear()
            await client.write_gatt_char(WRITE2, ch, response=False)
            try:
                await asyncio.wait_for(ack_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                print(f"  chunk {i}: ack timeout")
    elif args.mode == "response":
        for ch in chunks:
            await client.write_gatt_char(WRITE2, ch, response=True)
    elif args.mode == "window":
        for i, ch in enumerate(chunks):
            if acks["error"] is not None:
                print(f"  ABORT at chunk {i}: device error status 0x{acks['error']:02x}")
                aborted = True
                break
            while i - acks["data"] >= args.win:
                ack_event.clear()
                try:
                    await asyncio.wait_for(ack_event.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    print(f"  chunk {i}: window stall (acked={acks['data']})")
                    break
            await client.write_gatt_char(WRITE2, ch, response=False)
    elif args.mode == "gap":
        for ch in chunks:
            await client.write_gatt_char(WRITE2, ch, response=False)
            await asyncio.sleep(args.gap / 1000.0)
    else:  # nowait
        for ch in chunks:
            await client.write_gatt_char(WRITE2, ch, response=False)

    sent = time.monotonic()
    if aborted:
        return
    print(f"  sent in {sent - t0:.2f}s; waiting for 54 01 end-ack...")
    end_timeout = 10.0 if getattr(args, "repeat", 1) > 1 else 30.0
    try:
        while acks["end"] is None:
            ack_event.clear()
            await asyncio.wait_for(ack_event.wait(), timeout=end_timeout)
    except asyncio.TimeoutError:
        print(f"  no end-ack within {end_timeout:.0f}s")
    done = time.monotonic()
    end = acks["end"]
    end_label = "ok" if end == 1 else ("none" if end is None else f"FAIL({end})")
    print(
        f"  DONE: total {done - t0:.2f}s, data-acks={acks['data']}, end={end_label}, "
        f"last={acks['last'].hex() if acks['last'] else None}"
    )


async def cmd_send(args):
    dev = await _find(args.device)
    if dev is None:
        print("device not found (scan first; ensure HA released it)")
        return
    print(f"connecting {dev.name} {dev.address}")

    acks = {"data": 0, "end": None, "program": None, "error": None, "last": None}
    loop = asyncio.get_event_loop()
    ack_event = asyncio.Event()

    def on_notify(_c, data: bytearray):
        b = bytes(data)
        acks["last"] = b
        res = protocol.classify_notify(b)
        if res is not None:
            op, status = res
            if op == 0x00:
                if status in protocol.BULK_ACK_ERRORS:
                    acks["error"] = status
                else:
                    acks["data"] += 1
            elif op == 0x01:
                acks["end"] = status
            elif op == 0x06:
                acks["program"] = status
            else:
                print(f"  notify op=0x{op:02x} status={status}")
        else:
            acks["data"] += 1
        loop.call_soon_threadsafe(ack_event.set)

    repeat = getattr(args, "repeat", 1)
    interval = getattr(args, "interval", 5.0)
    async with BleakClient(dev) as client:
        await client.start_notify(NOTIFY, on_notify)
        base_rows = list(getattr(args, "rows", []) or [])
        for attempt in range(repeat):
            if repeat > 1:
                print(f"\n=== 전송 {attempt + 1}/{repeat} ===")
            if args.cmd == "status" and getattr(args, "vary", False) and attempt > 0:
                args.rows = base_rows[:-1] + [f"{base_rows[-1]} #{attempt}"]
            else:
                args.rows = base_rows
            text_data = _build_source(args)
            await _send_once(client, args, acks, ack_event, text_data)
            if attempt < repeat - 1:
                print(f"  {interval:.0f}s 대기...")
                await asyncio.sleep(interval)
        await asyncio.sleep(0.3)
        await client.stop_notify(NOTIFY)


def _capability(adv) -> str:
    mark = bytes([0x54, 0x42, 0x44])
    blobs = []
    for cid, data in (getattr(adv, "manufacturer_data", None) or {}).items():
        blobs.append(cid.to_bytes(2, "little") + bytes(data))
        blobs.append(bytes(data))
    for data in (getattr(adv, "service_data", None) or {}).values():
        blobs.append(bytes(data))
    for full in blobs:
        if mark in full:
            b = full[full.index(mark):]
            if len(b) >= 16:
                fun = int.from_bytes(b[14:16], "big")
                return f"  color_type={b[8]} fun_code=0x{fun:04x} gif={'Y' if fun & 0x04 else 'N'}"
    return ""


_COMPANY = {
    0x0006: "Microsoft",
    0x000A: "CSR/Qualcomm",
    0x004C: "Apple",
    0x0059: "Nordic",
    0x0075: "Samsung",
    0x0087: "Garmin",
    0x00E0: "Google",
    0x0157: "Huami",
    0x02E5: "Espressif",
}


def _mfr_hint(adv) -> str:
    for cid in getattr(adv, "manufacturer_data", None) or {}:
        return _COMPANY.get(cid, f"0x{cid:04X}")
    return ""


def rssi_key(rssi) -> int:
    return rssi if rssi is not None else -999


def sort_key(mfr: str, rssi):
    return (mfr == "", mfr, -rssi_key(rssi))


def scan_label(name: str | None, address: str, cap: str, rssi, mfr: str) -> str:
    sig = f"{rssi:>4}dBm" if rssi is not None else "   ?dBm"
    return f"📡 {sig}  {mfr or '알 수 없음'}  {name or '알 수 없음'}  ({address}){cap}"


async def cmd_scan(_args):
    found = await BleakScanner.discover(timeout=6.0, return_adv=True)
    rows = sorted(found.values(), key=lambda p: sort_key(_mfr_hint(p[1]), getattr(p[1], "rssi", None)))
    for d, adv in rows:
        print(scan_label(d.name, d.address, _capability(adv), getattr(adv, "rssi", None), _mfr_hint(adv)))


async def cmd_monitor(args):
    dev = await _find(args.device)
    if dev is None:
        print("device not found")
        return
    async with BleakClient(dev) as client:
        def on_notify(_c, data):
            print("notify <-", bytes(data).hex())
        await client.start_notify(NOTIFY, on_notify)
        print("monitoring 20s...")
        await asyncio.sleep(20)


def _rgb(s):
    parts = [int(x) for x in s.split(",")]
    return tuple(parts[:3])


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    m = sub.add_parser("monitor")
    m.add_argument("device", nargs="?")
    for name in ("text", "fill", "image", "gif", "status"):
        p = sub.add_parser(name)
        if name == "text":
            p.add_argument("text")
        if name in ("text", "status"):
            p.add_argument("--font", default=None, help="bundled font name or path")
            p.add_argument("--antialias", action="store_true")
        if name in ("image", "gif"):
            p.add_argument("path")
            p.add_argument("--fit", choices=["contain", "cover", "stretch"], default="contain")
        if name == "status":
            p.add_argument("rows", nargs="+", help="표시할 줄 (HA 상태표시 한 줄 = 프레임 1장)")
            p.add_argument("--device", default=None)
            p.add_argument("--rowcolors", default=None, help="줄별 색 'r,g,b;r,g,b' (부족하면 순환)")
            p.add_argument("--repeat", type=int, default=1, help="전송 반복 횟수 (interval tick 재현)")
            p.add_argument("--interval", type=float, default=5.0, help="반복 사이 대기 초")
            p.add_argument("--vary", action="store_true", help="매회 마지막 줄에 카운터를 붙여 내용 변경")
        else:
            p.add_argument("device", nargs="?")
        p.add_argument("--force", action="store_true", help="기기 unchanged(3) 응답을 무시하고 강제 전송")
        p.add_argument("--w", type=int, default=96)
        p.add_argument("--h", type=int, default=16)
        p.add_argument("--rgb", type=_rgb, default=(255, 255, 255))
        p.add_argument(
            "--mode",
            choices=["ackwait", "nowait", "response", "window", "gap"],
            default="window",
        )
        p.add_argument("--win", type=int, default=8)
        p.add_argument("--gap", type=float, default=5.0)
        p.add_argument("--speed", type=int, default=None)
        p.add_argument("--dwell", type=int, default=None)
        p.add_argument("--effects", type=int, default=0)
        p.add_argument("--srctype", type=int, default=None)
        p.add_argument("--gifmode", choices=["frames", "raw"], default="frames")
        p.add_argument("--maxframes", type=int, default=None)
        p.add_argument("--chroma", type=_rgb, default=None)
        p.add_argument("--tol", type=int, default=0)
        p.add_argument(
            "--order",
            choices=["rgb", "bgr", "grb", "gbr", "rbg", "brg"],
            default="rgb",
        )
    args = ap.parse_args()
    fn = {
        "scan": cmd_scan,
        "monitor": cmd_monitor,
        "text": cmd_send,
        "fill": cmd_send,
        "image": cmd_send,
        "gif": cmd_send,
        "status": cmd_send,
    }[args.cmd]
    asyncio.run(fn(args))


if __name__ == "__main__":
    main()
