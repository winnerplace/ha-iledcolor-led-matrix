#!/usr/bin/env python3
"""iLEDcolor BLE 검증 도구.

reverse-engineered 프로토콜(.claude/docs/analysis/iledcolor-ble-protocol-spec.md)을
실기에 검증한다. 의존성: pip install bleak

예시:
  python iledcolor_probe.py scan
  python iledcolor_probe.py info   AA:BB:CC:DD:EE:FF
  python iledcolor_probe.py on     AA:BB:CC:DD:EE:FF
  python iledcolor_probe.py off    AA:BB:CC:DD:EE:FF
  python iledcolor_probe.py bright AA:BB:CC:DD:EE:FF --level 5
  python iledcolor_probe.py raw    AA:BB:CC:DD:EE:FF 54090004050000 66 --char write1
  python iledcolor_probe.py monitor AA:BB:CC:DD:EE:FF
"""
import argparse
import asyncio

SERVICE = "0000a950-0000-1000-8000-00805f9b34fb"
WRITE1 = "0000a951-0000-1000-8000-00805f9b34fb"
WRITE2 = "0000a952-0000-1000-8000-00805f9b34fb"
NOTIFY = "0000a953-0000-1000-8000-00805f9b34fb"
MARKER = bytes([0x54, 0x42, 0x44])  # "TBD" 디바이스 식별 마커


def frame(op, payload):
    body = bytes([0x54, op]) + (len(payload) + 2).to_bytes(2, "big") + bytes(payload)
    return body + (sum(body) & 0xFFFF).to_bytes(2, "big")


def decode_capability(blob):
    b = bytes(blob)
    if len(b) < 17:
        return f"(blob {len(b)}B 너무 짧음: {b.hex()})"
    s16 = lambda i: int.from_bytes(b[i : i + 2], "big")
    fun = s16(15)
    bits = [
        (0x01, "시간"), (0x02, "분할"), (0x04, "gif"), (0x08, "미디어"),
        (0x10, "회전"), (0x20, "테두리"), (0x40, "비번"), (0x80, "리모컨"),
    ]
    feats = ",".join(n for m, n in bits if fun & m)
    return (
        f"screenTypeId={int.from_bytes(b[1:5],'big')} "
        f"WxH={s16(7)}x{s16(5)} colorType={b[9]}({'풀컬러' if b[9]==3 else '단색' if b[9] in (0,1) else '?'}) "
        f"versionCode={s16(11)}(밝기{'O' if s16(11)>=6 else 'X'}) customerId={s16(13)} "
        f"funCode=0x{fun:04x}[{feats}]"
    )


def find_marker(adv):
    for cid, data in (adv.manufacturer_data or {}).items():
        full = cid.to_bytes(2, "little") + bytes(data)
        if MARKER in full or MARKER in bytes(data):
            return ("manufacturer", cid, full)
    for uuid, data in (adv.service_data or {}).items():
        if MARKER in bytes(data):
            return ("service_data", uuid, bytes(data))
    return None


async def cmd_scan(args):
    from bleak import BleakScanner

    print("스캔 중 (10s)...")
    found = await BleakScanner.discover(timeout=10.0, return_adv=True)
    for addr, (dev, adv) in found.items():
        svc = adv.service_uuids or []
        is_a950 = any(SERVICE[:8] in (u or "").lower() for u in svc)
        mk = find_marker(adv)
        if not (is_a950 or mk) and not args.all:
            continue
        flag = "★후보" if (is_a950 or mk) else ""
        print(f"\n{flag} {addr}  name={dev.name!r}  rssi={adv.rssi}")
        if svc:
            print(f"   services: {svc}")
        for cid, data in (adv.manufacturer_data or {}).items():
            print(f"   mfr[0x{cid:04x}]: {bytes(data).hex()}")
        for uuid, data in (adv.service_data or {}).items():
            print(f"   svc_data[{uuid}]: {bytes(data).hex()}")
        if mk:
            kind, key, blob = mk
            print(f"   ▶ TBD 마커 in {kind}[{key}] → {decode_capability(blob)}")
    print("\n후보 없으면 --all 로 전체 표시, 또는 기기 앱 연결 끊고 재시도.")


def on_notify(_, data):
    print(f"   ◀ notify: {bytes(data).hex()}")


async def with_client(addr, fn):
    from bleak import BleakClient

    async with BleakClient(addr, timeout=20.0) as cli:
        print(f"연결됨: {addr}")
        svcs = cli.services
        chars = {c.uuid for s in svcs for c in s.characteristics}
        for u, name in [(WRITE1, "write1"), (WRITE2, "write2"), (NOTIFY, "notify")]:
            print(f"   {name} {u}: {'있음' if u in chars else '없음 ✗'}")
        if NOTIFY in chars:
            await cli.start_notify(NOTIFY, on_notify)
        await fn(cli)
        await asyncio.sleep(args_delay)


async def cmd_info(args):
    async def fn(cli):
        for s in cli.services:
            print(f" service {s.uuid}")
            for c in s.characteristics:
                print(f"   char {c.uuid} props={','.join(c.properties)}")
    await with_client(args.address, fn)


async def _send(cli, char_uuid, data, response=False):
    print(f"   ▶ write {char_uuid[-4:]}: {bytes(data).hex()}")
    await cli.write_gatt_char(char_uuid, bytes(data), response=response)


async def cmd_on(args):
    pkt = frame(0x0A, [1] + [0] * 9)
    await with_client(args.address, lambda c: _send(c, WRITE1, pkt))


async def cmd_off(args):
    pkt = frame(0x0A, [0] * 10)
    await with_client(args.address, lambda c: _send(c, WRITE1, pkt))


async def cmd_bright(args):
    pkt = frame(0x09, [10 - args.level, 0])
    await with_client(args.address, lambda c: _send(c, WRITE1, pkt))


async def cmd_raw(args):
    data = bytes.fromhex(args.hex.replace(" ", ""))
    char = WRITE2 if args.char == "write2" else WRITE1
    await with_client(args.address, lambda c: _send(c, char, data))


async def cmd_monitor(args):
    async def fn(_):
        print("notify 수신 대기 (Ctrl-C 종료)...")
        await asyncio.sleep(args.seconds)
    await with_client(args.address, fn)


args_delay = 3.0


def main():
    p = argparse.ArgumentParser(description="iLEDcolor BLE 검증 도구")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan").add_argument("--all", action="store_true", help="후보 외 전체 표시")
    sub.add_parser("info").add_argument("address")
    sub.add_parser("on").add_argument("address")
    sub.add_parser("off").add_argument("address")
    b = sub.add_parser("bright"); b.add_argument("address"); b.add_argument("--level", type=int, default=5, help="1~10")
    r = sub.add_parser("raw"); r.add_argument("address"); r.add_argument("hex"); r.add_argument("--char", choices=["write1", "write2"], default="write1")
    m = sub.add_parser("monitor"); m.add_argument("address"); m.add_argument("--seconds", type=int, default=60)
    a = p.parse_args()
    fns = {"scan": cmd_scan, "info": cmd_info, "on": cmd_on, "off": cmd_off,
           "bright": cmd_bright, "raw": cmd_raw, "monitor": cmd_monitor}
    asyncio.run(fns[a.cmd](a))


if __name__ == "__main__":
    main()
