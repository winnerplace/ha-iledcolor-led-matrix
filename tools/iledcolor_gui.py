#!/usr/bin/env python3
"""iLEDcolor 직접 디스플레이 GUI (Mac, HA 우회).

CLI(iledcolor_display.py) 대신 Tkinter UI로 스캔/연결/전송 테스트.
빌더 로직(_build_source: gif 끝 speed / chroma 키아웃 / maxframes / stay)은
iledcolor_display.py를 그대로 import해 재사용한다.

선행: BLE 권한 때문에 반드시 python.app 번들로 실행.
  /Users/ohilseung/miniconda3/python.app/Contents/MacOS/python \
      .claude/tools/iledcolor_gui.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import queue
import threading
import time
import tkinter as tk
from tkinter import colorchooser, filedialog, ttk
from types import SimpleNamespace

from bleak import BleakClient, BleakScanner
from PIL import Image, ImageTk

_HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("ildisp", _HERE / "iledcolor_display.py")
ildisp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ildisp)

bulk = ildisp.bulk
render = ildisp.render
WRITE1, WRITE2, NOTIFY = ildisp.WRITE1, ildisp.WRITE2, ildisp.NOTIFY
NAME_HINT = ildisp.NAME_HINT

EFFECTS = [
    ("정지", 0),
    ("좌 ←", 1),
    ("우 →", 2),
    ("위 ↑", 3),
    ("아래 ↓", 4),
    ("눈송이", 5),
    ("두루마리", 6),
    ("레이저", 7),
]


class BleWorker:
    def __init__(self, log):
        self._log = log
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.client: BleakClient | None = None
        self._dev = None
        self._ack: asyncio.Event | None = None
        self._acks = 0
        self._end = False

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro, done=None):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        if done is not None:
            fut.add_done_callback(lambda f: done(f))
        return fut

    def _on_notify(self, _c, data: bytearray):
        b = bytes(data)
        if b[:2] == b"\x54\x00":
            self._acks += 1
        elif b[:2] == b"\x54\x01":
            self._end = True
        if self._ack is not None:
            self._ack.set()

    async def scan(self):
        found = await BleakScanner.discover(timeout=6.0, return_adv=True)
        rows = []
        for dev, adv in found.values():
            name = dev.name or ""
            rows.append((dev, name, ildisp._capability(adv)))
        rows.sort(key=lambda r: (NAME_HINT not in (r[1] or "").lower(), r[1] or ""))
        return rows

    async def _ensure(self):
        if self.client is not None and self.client.is_connected:
            return
        if self._dev is None:
            raise RuntimeError("device not selected (scan + pick first)")
        self._log(f"connecting {self._dev.name} {self._dev.address}...")
        self.client = BleakClient(self._dev)
        await self.client.connect()
        self._ack = asyncio.Event()
        await self.client.start_notify(NOTIFY, self._on_notify)
        self._log("connected")

    async def disconnect(self):
        if self.client is not None and self.client.is_connected:
            await self.client.disconnect()
            self._log("disconnected")
        self.client = None

    async def send_raw(self, payload: bytes, char: str):
        await self._ensure()
        await self.client.write_gatt_char(char, payload, response=False)

    async def power(self, on: bool):
        await self.send_raw(bulk.simple_frame(0x0A, [1 if on else 0] + [0] * 9), WRITE1)
        self._log(f"power {'on' if on else 'off'}")

    async def brightness(self, level: int):
        level = max(1, min(10, level))
        await self.send_raw(bulk.simple_frame(0x09, [10 - level, 0]), WRITE1)
        self._log(f"brightness {level}/10")

    async def send_source(self, args, mode: str, win: int):
        await self._ensure()
        client = self.client
        mtu = getattr(client, "mtu_size", 0) or 23
        text_data = ildisp._build_source(args)
        header = bulk.legacy_header_frame(text_data)
        chunks = bulk.legacy_bulk_frames(text_data, mtu)
        self._log(f"mtu={mtu} data={len(text_data)}B chunks={len(chunks)} mode={mode}")
        self._acks = 0
        self._end = False
        t0 = time.monotonic()
        await client.write_gatt_char(WRITE1, header, response=False)
        if mode == "window":
            for i, ch in enumerate(chunks):
                while i - self._acks >= win:
                    self._ack.clear()
                    try:
                        await asyncio.wait_for(self._ack.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        break
                await client.write_gatt_char(WRITE2, ch, response=False)
        elif mode == "ackwait":
            for ch in chunks:
                self._ack.clear()
                await client.write_gatt_char(WRITE2, ch, response=False)
                try:
                    await asyncio.wait_for(self._ack.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
        else:  # nowait
            for ch in chunks:
                await client.write_gatt_char(WRITE2, ch, response=False)
        try:
            while not self._end:
                self._ack.clear()
                await asyncio.wait_for(self._ack.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            self._log("  no end-ack within 10s")
        self._log(f"DONE {time.monotonic() - t0:.2f}s acks={self._acks} end={self._end}")


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("iLEDcolor 직접 전송")
        self._logq: queue.Queue[str] = queue.Queue()
        self.worker = BleWorker(self._enqueue)
        self.devices: list = []
        self._scanning = False
        self._connected = False
        self.send_btns: list = []
        self._build()
        self._refresh_buttons()
        self._drain()
        self.root.after(300, self.on_scan)

    def _enqueue(self, msg: str):
        self._logq.put(msg)

    def _drain(self):
        while not self._logq.empty():
            self.log.configure(state="normal")
            self.log.insert("end", self._logq.get() + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(100, self._drain)

    def _color_btn(self, parent, initial=(255, 255, 255)):
        state = {"rgb": initial}
        sw = tk.Canvas(parent, width=26, height=20, highlightthickness=1,
                       highlightbackground="#888", bg="#%02x%02x%02x" % initial)

        def pick(_e=None):
            res = colorchooser.askcolor(color="#%02x%02x%02x" % state["rgb"])
            if res and res[0]:
                state["rgb"] = tuple(int(v) for v in res[0])
                sw.configure(bg="#%02x%02x%02x" % state["rgb"])

        sw.bind("<Button-1>", pick)
        return sw, state

    def _build(self):
        self.root.geometry("760x880")
        self.root.minsize(680, 720)
        style = ttk.Style()
        style.configure("Card.TLabelframe", padding=12)
        style.configure("Card.TLabelframe.Label", font=("", 12, "bold"))
        style.configure("Send.TButton", padding=(16, 4))
        style.configure("Nav.Treeview", rowheight=32, font=("", 13))

        conn = ttk.LabelFrame(self.root, text="연결", style="Card.TLabelframe")
        conn.pack(fill="x", padx=14, pady=(12, 6))
        self.status_var = tk.StringVar(value="🔴 연결 안 됨")
        ttk.Label(conn, textvariable=self.status_var, width=16, anchor="w").grid(row=0, column=0, sticky="w")
        self.dev_var = tk.StringVar()
        self.dev_cb = ttk.Combobox(conn, textvariable=self.dev_var, state="readonly")
        self.dev_cb.grid(row=0, column=1, sticky="we", padx=6)
        self.dev_cb.bind("<<ComboboxSelected>>", lambda _e: self._refresh_buttons())
        self.scan_btn = ttk.Button(conn, text="스캔", command=self.on_scan)
        self.scan_btn.grid(row=0, column=2, padx=2)
        self.connect_btn = ttk.Button(conn, text="연결", command=self.on_connect)
        self.connect_btn.grid(row=0, column=3, padx=2)
        self.disconnect_btn = ttk.Button(conn, text="해제", command=self.on_disconnect)
        self.disconnect_btn.grid(row=0, column=4, padx=2)
        conn.columnconfigure(1, weight=1)
        pw = ttk.Frame(conn)
        pw.grid(row=1, column=0, columnspan=5, sticky="we", pady=(10, 0))
        b_on = ttk.Button(pw, text="전원 ON", command=lambda: self.worker.submit(self.worker.power(True)))
        b_on.pack(side="left")
        b_off = ttk.Button(pw, text="전원 OFF", command=lambda: self.worker.submit(self.worker.power(False)))
        b_off.pack(side="left", padx=(4, 16))
        ttk.Label(pw, text="밝기").pack(side="left")
        self.bright_var = tk.IntVar(value=10)
        ttk.Scale(pw, from_=1, to=10, variable=self.bright_var, length=130, orient="horizontal").pack(side="left", padx=6)
        b_br = ttk.Button(pw, text="적용", command=lambda: self.worker.submit(self.worker.brightness(int(self.bright_var.get()))))
        b_br.pack(side="left")
        self.send_btns += [b_on, b_off, b_br]

        common = ttk.LabelFrame(self.root, text="공통 설정", style="Card.TLabelframe")
        common.pack(fill="x", padx=14, pady=6)
        common.columnconfigure(1, weight=1)
        self.w_var = tk.IntVar(value=96)
        self.h_var = tk.IntVar(value=16)
        size = self._row(common, 0, "패널 크기")
        ttk.Entry(size, textvariable=self.w_var, width=6).pack(side="left")
        ttk.Label(size, text="×").pack(side="left", padx=4)
        ttk.Entry(size, textvariable=self.h_var, width=6).pack(side="left")
        self.eff_var = tk.StringVar(value=EFFECTS[0][0])
        eff = self._row(common, 1, "효과 (슬라이드)")
        ttk.Combobox(eff, textvariable=self.eff_var, width=12, state="readonly",
                     values=[e[0] for e in EFFECTS]).pack(side="left")
        self.speed_var = tk.StringVar(value="1")
        self.dwell_var = tk.StringVar(value="")
        sp = self._row(common, 2, "속도 / 정지")
        ttk.Entry(sp, textvariable=self.speed_var, width=6).pack(side="left")
        ttk.Label(sp, text="속도").pack(side="left", padx=(4, 14))
        ttk.Entry(sp, textvariable=self.dwell_var, width=6).pack(side="left")
        ttk.Label(sp, text="정지 (0=연속)").pack(side="left", padx=4)
        self.mode_var = tk.StringVar(value="window")
        self.win_var = tk.IntVar(value=32)
        md = self._row(common, 3, "전송 모드")
        ttk.Combobox(md, textvariable=self.mode_var, width=9, state="readonly",
                     values=["window", "nowait", "ackwait"]).pack(side="left")
        ttk.Label(md, text="win").pack(side="left", padx=(14, 4))
        ttk.Entry(md, textvariable=self.win_var, width=5).pack(side="left")

        prev = ttk.LabelFrame(self.root, text="미리보기", style="Card.TLabelframe")
        prev.pack(fill="x", padx=14, pady=6)
        self.preview = tk.Canvas(prev, height=80, bg="#000000", highlightthickness=1,
                                 highlightbackground="#444")
        self.preview.pack()
        self._anim_job = None
        self._frames = []

        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=14, pady=6)
        nav = ttk.Treeview(body, show="tree", selectmode="browse", height=4, style="Nav.Treeview")
        nav.column("#0", width=120)
        nav.pack(side="left", fill="y", padx=(0, 12))
        self.content = ttk.Frame(body)
        self.content.pack(side="left", fill="both", expand=True)
        self.panes = {}
        for key, label in [("text", "📝 텍스트"), ("image", "🖼 이미지"), ("gif", "🎞 GIF"), ("fill", "🎨 단색")]:
            nav.insert("", "end", iid=key, text=f" {label}")
            card = ttk.LabelFrame(self.content, text=label, style="Card.TLabelframe")
            card.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.panes[key] = card
            getattr(self, f"_pane_{key}")(card)
        nav.bind("<<TreeviewSelect>>", lambda _e: self.panes[nav.selection()[0]].tkraise())
        nav.selection_set("text")

        logf = ttk.LabelFrame(self.root, text="로그", style="Card.TLabelframe")
        logf.pack(fill="both", expand=False, padx=14, pady=(6, 12))
        self.log = tk.Text(logf, height=7, state="disabled", relief="flat",
                           bg="#1e1e1e", fg="#d4d4d4", insertbackground="#d4d4d4")
        self.log.pack(fill="both", expand=True)

    def _row(self, parent, r, label):
        ttk.Label(parent, text=label, width=14, anchor="w").grid(row=r, column=0, sticky="w", pady=6)
        cell = ttk.Frame(parent)
        cell.grid(row=r, column=1, sticky="w", pady=6)
        return cell

    def _pane_text(self, f):
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="문구").grid(row=0, column=0, sticky="w", pady=6)
        self.text_var = tk.StringVar(value="안녕")
        ttk.Entry(f, textvariable=self.text_var).grid(row=0, column=1, sticky="we", padx=6)
        self.text_color_btn, self.text_color = self._color_btn(f)
        self.text_color_btn.grid(row=0, column=2, padx=4)
        bar = ttk.Frame(f)
        bar.grid(row=1, column=1, sticky="w", padx=6, pady=(12, 0))
        ttk.Button(bar, text="미리보기", command=self.preview_text).pack(side="left")
        sb = ttk.Button(bar, text="전송", style="Send.TButton", command=self.send_text)
        sb.pack(side="left", padx=6)
        self.send_btns.append(sb)

    def _pane_image(self, f):
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="파일").grid(row=0, column=0, sticky="w", pady=6)
        self.img_path = tk.StringVar()
        ttk.Entry(f, textvariable=self.img_path).grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(f, text="찾기", command=lambda: self._browse(self.img_path)).grid(row=0, column=2)
        ttk.Label(f, text="맞춤").grid(row=1, column=0, sticky="w", pady=6)
        self.img_fit = tk.StringVar(value="contain")
        ttk.Combobox(f, textvariable=self.img_fit, width=10, state="readonly",
                     values=["contain", "cover", "stretch"]).grid(row=1, column=1, sticky="w", padx=6)
        bar = ttk.Frame(f)
        bar.grid(row=2, column=1, sticky="w", padx=6, pady=(12, 0))
        ttk.Button(bar, text="미리보기", command=self.preview_image).pack(side="left")
        sb = ttk.Button(bar, text="전송", style="Send.TButton", command=self.send_image)
        sb.pack(side="left", padx=6)
        self.send_btns.append(sb)

    def _pane_gif(self, f):
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="파일").grid(row=0, column=0, sticky="w", pady=6)
        self.gif_path = tk.StringVar()
        ttk.Entry(f, textvariable=self.gif_path).grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(f, text="찾기", command=lambda: self._browse(self.gif_path)).grid(row=0, column=2)
        ttk.Label(f, text="맞춤 / 프레임").grid(row=1, column=0, sticky="w", pady=6)
        r1 = ttk.Frame(f)
        r1.grid(row=1, column=1, sticky="w", padx=6)
        self.gif_fit = tk.StringVar(value="contain")
        ttk.Combobox(r1, textvariable=self.gif_fit, width=9, state="readonly",
                     values=["contain", "cover", "stretch"]).pack(side="left")
        ttk.Label(r1, text="정지").pack(side="left", padx=(12, 2))
        self.gif_stay = tk.IntVar(value=10)
        ttk.Entry(r1, textvariable=self.gif_stay, width=4).pack(side="left")
        ttk.Label(r1, text="max").pack(side="left", padx=(12, 2))
        self.gif_maxf = tk.StringVar(value="")
        ttk.Entry(r1, textvariable=self.gif_maxf, width=4).pack(side="left")
        ttk.Label(f, text="배경 제거").grid(row=2, column=0, sticky="w", pady=6)
        r2 = ttk.Frame(f)
        r2.grid(row=2, column=1, sticky="w", padx=6)
        self.gif_keyon = tk.BooleanVar(value=False)
        ttk.Checkbutton(r2, text="켜기", variable=self.gif_keyon).pack(side="left")
        self.gif_chroma_btn, self.gif_chroma = self._color_btn(r2, (255, 255, 255))
        self.gif_chroma_btn.pack(side="left", padx=6)
        ttk.Label(r2, text="tol").pack(side="left", padx=(8, 2))
        self.gif_tol = tk.IntVar(value=20)
        ttk.Entry(r2, textvariable=self.gif_tol, width=4).pack(side="left")
        bar = ttk.Frame(f)
        bar.grid(row=3, column=1, sticky="w", padx=6, pady=(12, 0))
        ttk.Button(bar, text="미리보기", command=self.preview_gif).pack(side="left")
        sb = ttk.Button(bar, text="전송", style="Send.TButton", command=self.send_gif)
        sb.pack(side="left", padx=6)
        self.send_btns.append(sb)

    def _pane_fill(self, f):
        ttk.Label(f, text="색상").grid(row=0, column=0, sticky="w", pady=6)
        self.fill_color_btn, self.fill_color = self._color_btn(f, (255, 0, 0))
        self.fill_color_btn.grid(row=0, column=1, sticky="w", padx=6)
        bar = ttk.Frame(f)
        bar.grid(row=1, column=1, sticky="w", padx=6, pady=(12, 0))
        ttk.Button(bar, text="미리보기", command=self.preview_fill).pack(side="left")
        sb = ttk.Button(bar, text="전송", style="Send.TButton", command=self.send_fill)
        sb.pack(side="left", padx=6)
        self.send_btns.append(sb)

    def _browse(self, var):
        path = filedialog.askopenfilename(
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"), ("All", "*.*")]
        )
        if path:
            var.set(path)

    def _refresh_buttons(self):
        has_dev = self.dev_cb.current() >= 0
        self.scan_btn.configure(state="disabled" if self._scanning else "normal")
        self.connect_btn.configure(
            state="normal" if (has_dev and not self._connected and not self._scanning) else "disabled")
        self.disconnect_btn.configure(state="normal" if self._connected else "disabled")
        for b in self.send_btns:
            b.configure(state="normal" if self._connected else "disabled")

    def on_scan(self):
        self._scanning = True
        self._refresh_buttons()
        self._enqueue("스캔 중 (6초)...")
        self.worker.submit(self.worker.scan(), self._scan_done)

    def _scan_done(self, fut):
        try:
            rows = fut.result()
        except Exception as err:
            rows = []
            self._enqueue(f"scan error: {err}")
        self.devices = rows
        labels = [f"{name or '(이름 없음)'}  {dev.address}{cap}" for dev, name, cap in rows]
        self.root.after(0, lambda: self._fill_devices(labels))

    def _fill_devices(self, labels):
        self.dev_cb["values"] = labels
        if labels:
            self.dev_cb.current(0)
        self._scanning = False
        self._enqueue(f"기기 {len(labels)}개 발견")
        self._refresh_buttons()

    def on_connect(self):
        idx = self.dev_cb.current()
        if idx < 0 or idx >= len(self.devices):
            self._enqueue("기기를 먼저 선택하세요")
            return
        self.worker._dev = self.devices[idx][0]
        self._conn_name = self.devices[idx][1] or self.devices[idx][0].address
        self.status_var.set("🟡 연결 중…")
        self.worker.submit(self.worker._ensure(), self._conn_done)

    def _conn_done(self, fut):
        try:
            fut.result()
            self._connected = True
            self.root.after(0, self._on_connected)
        except Exception as err:
            self._connected = False
            self._enqueue(f"connect error: {err}")
            self.root.after(0, lambda: (self.status_var.set("🔴 연결 실패"), self._refresh_buttons()))

    def _on_connected(self):
        self.status_var.set(f"🟢 {self._conn_name}")
        self._refresh_buttons()

    def on_disconnect(self):
        self.worker.submit(self.worker.disconnect())
        self._connected = False
        self.status_var.set("🔴 연결 안 됨")
        self._refresh_buttons()

    def _eff_code(self):
        return dict(EFFECTS).get(self.eff_var.get(), 0)

    def _speed_val(self):
        s = self.speed_var.get().strip()
        return int(s) if s else None

    def _dwell_val(self):
        s = self.dwell_var.get().strip()
        return int(s) if s else None

    def _common(self, cmd, **extra):
        base = dict(
            cmd=cmd, w=self.w_var.get(), h=self.h_var.get(),
            rgb=(255, 255, 255), text=None, path=None, fit="contain",
            speed=self._speed_val(), dwell=self._dwell_val(), effects=self._eff_code(),
            srctype=None, gifmode="frames", maxframes=None, chroma=None,
            tol=0, order="rgb",
        )
        base.update(extra)
        return SimpleNamespace(**base)

    def _args_text(self):
        return self._common("text", text=self.text_var.get(), rgb=self.text_color["rgb"])

    def _args_image(self):
        if not self.img_path.get():
            self._enqueue("이미지: 파일을 선택하세요")
            return None
        return self._common("image", path=self.img_path.get(), fit=self.img_fit.get())

    def _args_gif(self):
        if not self.gif_path.get():
            self._enqueue("GIF: 파일을 선택하세요")
            return None
        maxf = self.gif_maxf.get().strip()
        return self._common(
            "gif", path=self.gif_path.get(), fit=self.gif_fit.get(),
            dwell=self.gif_stay.get(), maxframes=int(maxf) if maxf else None,
            tol=self.gif_tol.get(),
            chroma=self.gif_chroma["rgb"] if self.gif_keyon.get() else None,
        )

    def _args_fill(self):
        return self._common("fill", rgb=self.fill_color["rgb"])

    def _go(self, args):
        if args is None:
            return
        self.worker.submit(self.worker.send_source(args, self.mode_var.get(), self.win_var.get()))

    def send_text(self):
        self._go(self._args_text())

    def send_image(self):
        self._go(self._args_image())

    def send_gif(self):
        self._go(self._args_gif())

    def send_fill(self):
        self._go(self._args_fill())

    def preview_text(self):
        self._preview(self._args_text())

    def preview_image(self):
        self._preview(self._args_image())

    def preview_gif(self):
        self._preview(self._args_gif())

    def preview_fill(self):
        self._preview(self._args_fill())

    def _preview(self, args):
        if args is None:
            return

        def work():
            try:
                grids, gspeed, _ = ildisp._build_grids(args)
            except Exception as err:
                self._enqueue(f"preview error: {err}")
                return
            speed = args.speed if args.speed is not None else gspeed
            self.root.after(0, lambda: self._show_preview(grids, args.effects, speed))

        threading.Thread(target=work, daemon=True).start()

    def _show_preview(self, grids, effect=0, speed=3):
        self._stop_anim()
        if not grids:
            return
        self._pv_grids = grids
        self._pv_effect = effect
        self._pv_off = 0
        self._pv_i = 0
        self._draw_pv()
        scroll = effect in (1, 2, 3, 4)
        if scroll or len(grids) > 1:
            self._pv_interval = max(20, 130 - int(speed) * 5) if scroll else 150
            self._anim_job = self.root.after(self._pv_interval, self._tick_pv)

    def _tick_pv(self):
        if len(self._pv_grids) > 1:
            self._pv_i = (self._pv_i + 1) % len(self._pv_grids)
        if self._pv_effect in (1, 2, 3, 4):
            self._pv_off += 1
        self._draw_pv()
        self._anim_job = self.root.after(self._pv_interval, self._tick_pv)

    def _draw_pv(self):
        self._blit(self._scroll(self._pv_grids[self._pv_i], self._pv_effect, self._pv_off))

    @staticmethod
    def _scroll(g, effect, off):
        h = len(g)
        w = len(g[0]) if h else 0
        if effect not in (1, 2, 3, 4) or not w:
            return g
        if effect == 1:
            return [[g[y][(x + off) % w] for x in range(w)] for y in range(h)]
        if effect == 2:
            return [[g[y][(x - off) % w] for x in range(w)] for y in range(h)]
        if effect == 3:
            return [[g[(y + off) % h][x] for x in range(w)] for y in range(h)]
        return [[g[(y - off) % h][x] for x in range(w)] for y in range(h)]

    def _blit(self, g):
        h = len(g)
        w = len(g[0]) if h else 0
        if not w or not h:
            return
        scale = max(1, min(560 // w, 80 // h))
        img = Image.new("RGB", (w, h))
        img.putdata([(px[0], px[1], px[2]) for row in g for px in row])
        img = img.resize((w * scale, h * scale), Image.NEAREST)
        self._pv_photo = ImageTk.PhotoImage(img)
        cv = self.preview
        cv.configure(width=w * scale, height=h * scale)
        cv.delete("all")
        cv.create_image(0, 0, anchor="nw", image=self._pv_photo)

    def _stop_anim(self):
        if self._anim_job is not None:
            self.root.after_cancel(self._anim_job)
            self._anim_job = None


def main():
    root = tk.Tk()
    App(root)
    root.lift()
    root.attributes("-topmost", True)
    root.after(500, lambda: root.attributes("-topmost", False))
    root.mainloop()


if __name__ == "__main__":
    main()
