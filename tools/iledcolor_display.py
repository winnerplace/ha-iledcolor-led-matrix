#!/usr/bin/env python3
"""iLEDcolor 직접 디스플레이 테스트 (Mac ↔ 기기, HA 우회).

목적: legacy 벌크 전송을 bleak로 직접 보내며 속도/ACK 전략 실험.
의존성: pip install bleak pillow

선행: HA가 기기 BLE를 점유 중이면 충돌. HA 통합을 비활성화하거나 기기를 HA 범위 밖으로.

예시:
  python iledcolor_display.py scan
  python iledcolor_display.py text  "Hi" --w 96 --h 16 --mode ackwait
  python iledcolor_display.py text  "Hi" --w 96 --h 16 --mode nowait
  python iledcolor_display.py fill  --w 96 --h 16 --rgb 255,0,0 --mode response
  python iledcolor_display.py monitor
모드: ackwait(청크마다 notify 1개 대기) / nowait(무대기 연속) / response(write-with-response)
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import pathlib
import time

from bleak import BleakClient, BleakScanner

SERVICE = "0000a950-0000-1000-8000-00805f9b34fb"
WRITE1 = "0000a951-0000-1000-8000-00805f9b34fb"
WRITE2 = "0000a952-0000-1000-8000-00805f9b34fb"
NOTIFY = "0000a953-0000-1000-8000-00805f9b34fb"
NAME_HINT = "iledcolor"

_CC = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "iledcolor"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"il_{name}", _CC / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bulk = _load("bulk")
render = _load("render")


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


def _build_grids(args):
    w, h = args.w, args.h
    speed = 50
    raw_pixel = None
    if args.cmd == "text":
        grids = [render.rasterize_text(args.text, w, h, color=args.rgb)]
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
        if args.cmd == "gif":
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


async def cmd_send(args):
    dev = await _find(args.device)
    if dev is None:
        print("device not found (scan first; ensure HA released it)")
        return
    print(f"connecting {dev.name} {dev.address}")

    acks = {"data": 0, "end": False, "last": None}
    loop = asyncio.get_event_loop()
    ack_event = asyncio.Event()

    def on_notify(_c, data: bytearray):
        b = bytes(data)
        acks["last"] = b
        if b[:2] == bytes([0x54, 0x00]):
            acks["data"] += 1
            loop.call_soon_threadsafe(ack_event.set)
        elif b[:2] == bytes([0x54, 0x01]):
            acks["end"] = True
            loop.call_soon_threadsafe(ack_event.set)

    async with BleakClient(dev) as client:
        mtu = getattr(client, "mtu_size", 0) or 23
        await client.start_notify(NOTIFY, on_notify)
        text_data = _build_source(args)
        header = bulk.legacy_header_frame(text_data)
        chunks = bulk.legacy_bulk_frames(text_data, mtu)
        print(f"mtu={mtu} textData={len(text_data)}B chunks={len(chunks)} mode={args.mode}")

        t0 = time.monotonic()
        await client.write_gatt_char(WRITE1, header, response=False)

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
        print(f"sent in {sent - t0:.2f}s; waiting for 54 01 end-ack...")
        try:
            while not acks["end"]:
                await asyncio.wait_for(ack_event.wait(), timeout=30.0)
                ack_event.clear()
        except asyncio.TimeoutError:
            print("  no end-ack within 30s")
        done = time.monotonic()
        print(f"DONE: total {done - t0:.2f}s, data-acks={acks['data']}, end={acks['end']}, last={acks['last'].hex() if acks['last'] else None}")
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


async def cmd_scan(_args):
    found = await BleakScanner.discover(timeout=6.0, return_adv=True)
    for d, adv in found.values():
        print(f"{d.address}  {d.name}{_capability(adv)}")


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
    for name in ("text", "fill", "image", "gif"):
        p = sub.add_parser(name)
        if name == "text":
            p.add_argument("text")
        if name in ("image", "gif"):
            p.add_argument("path")
            p.add_argument("--fit", choices=["contain", "cover", "stretch"], default="contain")
        p.add_argument("device", nargs="?")
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
    }[args.cmd]
    asyncio.run(fn(args))


if __name__ == "__main__":
    main()
