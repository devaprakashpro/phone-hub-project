#!/usr/bin/env python3
"""
PhoneHub desktop — self-contained companion server.

Runs its own WebSocket server (no KDE Connect, no scrcpy). The Android app
connects to it over the LAN and we speak the protocol in docs/PROTOCOL.md.

Thread model:
  * main thread  -> GTK4 / libadwaita UI
  * server thread -> asyncio websockets server
Cross-thread: incoming frames -> GLib.idle_add(...) onto the UI thread;
outgoing frames -> asyncio.run_coroutine_threadsafe(...) onto the server loop.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio, Gdk

import asyncio
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time

import websockets  # v10.x
import segno
from mirror import MirrorWindow
from kdeconnect import KdeConnect

PORT = 8766
CONFIG_DIR = os.path.expanduser("~/.config/phonehub")
PEERS_FILE = os.path.join(CONFIG_DIR, "peers.json")
QR_PATH = os.path.join(CONFIG_DIR, "pair-qr.png")
DOWNLOADS = os.path.expanduser("~/Downloads")
APP_ID = "in.devaprakash.PhoneHub.Desktop"

# Palette shared with the mobile app (PhoneHubMobile/src/theme.ts) — keep in sync.
PAL = {
    "bg": "#0b0d14", "bgElev": "#10131d", "card": "#151926", "cardSoft": "#1b2030",
    "border": "#272d3f", "accent": "#7c8bff", "accentDim": "#4b56b8",
    "accentSoft": "rgba(124,139,255,0.14)", "onAccent": "#0a0e22",
    "text": "#eef1f9", "sub": "#9098ad", "faint": "#5a6178", "danger": "#ff5d72",
}

CSS = f"""
window.ph-root, .ph-root {{ background-color: {PAL['bg']}; color: {PAL['text']}; }}
.ph-headerbar {{ background-color: {PAL['bg']}; box-shadow: none; border: none; min-height: 0; }}
.ph-brand {{ font-size: 17px; font-weight: 800; color: {PAL['text']}; }}
.ph-brand-mark {{ color: {PAL['accent']}; }}
.ph-title {{ font-size: 16px; font-weight: 700; color: {PAL['text']}; }}
.ph-sub {{ font-size: 12px; color: {PAL['sub']}; }}
.ph-faint {{ font-size: 11px; color: {PAL['faint']}; letter-spacing: 1px; }}
.ph-accent {{ color: {PAL['accent']}; }}
.ph-danger {{ color: {PAL['danger']}; }}
.ph-card {{ background-color: {PAL['card']}; border: 1px solid {PAL['border']}; border-radius: 18px; padding: 16px; }}
.ph-soft {{ background-color: {PAL['cardSoft']}; border: 1px solid {PAL['border']}; border-radius: 14px; padding: 14px; }}
.ph-preview {{ background-color: #070811; border: 1px solid {PAL['border']}; border-radius: 14px; padding: 18px; }}
.ph-bigicon {{ font-size: 46px; color: {PAL['accent']}; }}
.ph-metricval {{ font-size: 18px; font-weight: 800; color: {PAL['text']}; }}
.ph-pill {{ border: 1px solid {PAL['accent']}; border-radius: 999px; padding: 3px 11px; }}
.ph-pill label {{ font-size: 11px; font-weight: 700; color: {PAL['accent']}; }}
.ph-pill box.dot {{ min-width: 7px; min-height: 7px; border-radius: 4px; background: {PAL['accent']}; }}
.ph-pill.sub {{ border-color: {PAL['sub']}; }}
.ph-pill.sub label {{ color: {PAL['sub']}; }}
.ph-pill.sub box.dot {{ background: {PAL['sub']}; }}
.ph-pill.danger {{ border-color: {PAL['danger']}; }}
.ph-pill.danger label {{ color: {PAL['danger']}; }}
.ph-pill.danger box.dot {{ background: {PAL['danger']}; }}
button.ph-primary {{ background: {PAL['accent']}; color: {PAL['onAccent']}; font-weight: 800;
    border-radius: 14px; border: none; padding: 12px; box-shadow: none; }}
button.ph-primary:hover {{ background: #93a0ff; }}
button.ph-ghost {{ background: {PAL['cardSoft']}; color: {PAL['text']}; font-weight: 700;
    border: 1px solid {PAL['border']}; border-radius: 14px; padding: 12px; box-shadow: none; }}
button.ph-ghost:hover {{ background: #232a3b; }}
button.ph-danger {{ background: {PAL['danger']}; color: #fff; font-weight: 800;
    border-radius: 14px; border: none; padding: 12px; }}
button.ph-iconbtn {{ background: {PAL['cardSoft']}; border: 1px solid {PAL['border']};
    border-radius: 14px; color: {PAL['accent']}; min-width: 46px; padding: 8px; }}
.ph-tabbar {{ background-color: {PAL['bgElev']}; border-top: 1px solid {PAL['border']}; }}
button.ph-tab {{ background: transparent; border: none; box-shadow: none; padding: 8px 4px; border-radius: 0; }}
button.ph-tab label.ico {{ font-size: 18px; color: {PAL['faint']}; }}
button.ph-tab label.txt {{ font-size: 11px; font-weight: 600; color: {PAL['faint']}; }}
button.ph-tab.active label.ico, button.ph-tab.active label.txt {{ color: {PAL['accent']}; }}
.ph-track {{ background-color: {PAL['border']}; border-radius: 3px; min-height: 5px; }}
.ph-fill {{ background-color: {PAL['accent']}; border-radius: 3px; min-height: 5px; }}
.ph-sendbox {{ background-color: {PAL['accentSoft']}; border: 1px solid {PAL['accentDim']}; border-radius: 14px; padding: 22px; }}
.ph-divider {{ background-color: {PAL['border']}; min-height: 1px; }}
/* wide-window side rail (shown instead of the bottom tabbar when roomy) */
.ph-sidebar {{ background-color: {PAL['bgElev']}; border-right: 1px solid {PAL['border']}; padding: 12px 10px; }}
button.ph-side {{ background: transparent; border: none; box-shadow: none; border-radius: 12px; padding: 11px 14px; margin: 2px 4px; }}
button.ph-side:hover {{ background: {PAL['cardSoft']}; }}
button.ph-side label.ico {{ font-size: 17px; color: {PAL['faint']}; }}
button.ph-side label.txt {{ font-size: 14px; font-weight: 600; color: {PAL['sub']}; }}
button.ph-side.active {{ background: {PAL['accentSoft']}; }}
button.ph-side.active label.ico, button.ph-side.active label.txt {{ color: {PAL['accent']}; }}
"""


def install_css():
    provider = Gtk.CssProvider()
    try:
        provider.load_from_string(CSS)          # GTK >= 4.12
    except (AttributeError, TypeError):
        provider.load_from_data(CSS.encode())   # older GTK
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def load_peers():
    try:
        with open(PEERS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_peers(p):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(PEERS_FILE, "w") as f:
        json.dump(p, f)


class Server(threading.Thread):
    """asyncio websockets server living on its own thread."""

    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app
        self.loop = None
        self.ws = None              # the one connected phone
        self.pin = f"{secrets.randbelow(900000) + 100000}"   # fixed for this session
        self.host = lan_ip()
        self.peers = load_peers()
        self._inbox = {}            # transferId -> open file handle

    def build_qr(self):
        """Render the pairing QR ({host,port,pin}) to QR_PATH."""
        os.makedirs(CONFIG_DIR, exist_ok=True)
        payload = json.dumps({"host": self.host, "port": PORT, "pin": self.pin})
        segno.make(payload, error="m").save(QR_PATH, scale=7, border=2, dark="#0b1020")
        return QR_PATH

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._serve())
        self.loop.run_forever()

    async def _serve(self):
        await websockets.serve(self._handle, "0.0.0.0", PORT, max_size=None)
        self.build_qr()
        print(f"[server] READY host={self.host} port={PORT} pin={self.pin}", file=sys.stderr, flush=True)
        self.app.ui(lambda: self.app.show_qr(QR_PATH, self.pin, self.host))

    # ---- outbound (called from UI thread) ----
    def send(self, obj):
        if self.ws and self.loop:
            asyncio.run_coroutine_threadsafe(self._send(obj), self.loop)

    async def _send(self, obj):
        try:
            await self.ws.send(json.dumps(obj))
        except Exception:
            pass

    def send_bytes(self, data):
        if self.ws and self.loop:
            asyncio.run_coroutine_threadsafe(self._send_bytes(data), self.loop)

    async def _send_bytes(self, data):
        try:
            await self.ws.send(data)   # bytes → binary WebSocket frame
        except Exception:
            pass

    def push_file(self, path):
        """Stream a local file to the phone: file_offer + 0x01 chunks + file_done.
        Matches the phone's DeviceServices inbox (raw = [0x01][8 ascii tid][bytes])."""
        tid = secrets.token_hex(4)              # 8 hex chars = 8 ascii bytes
        name = os.path.basename(path)
        try:
            size = os.path.getsize(path)
        except OSError:
            size = -1
        self.send({"t": "file_offer", "transferId": tid, "name": name, "size": size})

        def worker():
            try:
                tb = tid.encode("ascii")
                with open(path, "rb") as f:
                    while True:
                        chunk = f.read(60 * 1024)
                        if not chunk:
                            break
                        self.send_bytes(bytes([0x01]) + tb + chunk)
                self.send({"t": "file_done", "transferId": tid})
            except Exception as e:
                print(f"[server] push_file error: {e!r}", file=sys.stderr, flush=True)
        threading.Thread(target=worker, daemon=True).start()

    # ---- connection handler ----
    async def _handle(self, ws, path=None):
        # Don't claim self.ws on raw connect: the phone may race two sockets
        # (LAN + USB tunnel) and cancel the loser. We claim the link only when
        # a "hello" arrives on it, so a cancelled racer can't clobber the winner.
        peer = getattr(ws, "remote_address", None)
        print(f"[server] socket OPEN from {peer}", file=sys.stderr, flush=True)
        device = {"id": None, "name": "phone", "authed": False}
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    # A decode/render error in the binary path must never kill
                    # the control socket — isolate it.
                    try:
                        self._on_binary(raw)
                    except Exception as e:
                        print(f"[server] binary handler error: {e!r}", file=sys.stderr, flush=True)
                    continue
                msg = json.loads(raw)
                print(f"[server] recv t={msg.get('t')!r}", file=sys.stderr, flush=True)
                await self._on_control(ws, msg, device)
        except Exception as e:
            print(f"[server] socket error from {peer}: {e!r}", file=sys.stderr, flush=True)
        finally:
            print(f"[server] socket CLOSE from {peer}", file=sys.stderr, flush=True)
            if self.ws is ws:
                self.ws = None
            self.app.ui(lambda: self.app.set_connected(False, "Phone disconnected"))

    async def _on_control(self, ws, msg, device):
        t = msg.get("t")
        if t == "hello":
            self.ws = ws            # this socket is the live link
            device["id"] = msg.get("deviceId")
            device["name"] = msg.get("name", "phone")
            token = msg.get("token")
            known = self.peers.get(device["id"])
            if known and token and token == known.get("token"):
                device["authed"] = True
                await self._send_now(ws, {"t": "paired", "token": token})
                await self._ready(ws, device)
            else:
                # PIN is fixed for the session and already in the QR; just ask.
                await self._send_now(ws, {"t": "need_pin"})
        elif t == "auth":
            if msg.get("pin") == self.pin:
                token = secrets.token_hex(16)
                self.peers[device["id"]] = {"name": device["name"], "token": token}
                save_peers(self.peers)
                device["authed"] = True
                await self._send_now(ws, {"t": "paired", "token": token})
                await self._ready(ws, device)
            else:
                await self._send_now(ws, {"t": "auth_fail"})
        elif not device["authed"]:
            return  # ignore everything until authed
        elif t == "battery":
            self.app.ui(lambda: self.app.set_battery(msg.get("level"), msg.get("charging")))
        elif t == "notification":
            self.app.ui(lambda: self.app.add_notification(msg))
        elif t == "clipboard":
            self.app.ui(lambda: self.app.recv_clipboard(msg.get("text", "")))
        elif t == "sms_list":
            self.app.ui(lambda: self.app.show_sms(msg.get("threads", [])))
        elif t == "file_offer":
            self._inbox[msg["transferId"]] = open(
                os.path.join(DOWNLOADS, os.path.basename(msg.get("name", "file"))), "wb")
            await self._send_now(ws, {"t": "file_accept", "transferId": msg["transferId"]})
        elif t == "file_done":
            fh = self._inbox.pop(msg["transferId"], None)
            if fh:
                fh.close()
                self.app.ui(lambda: self.app.toast(f"Received {os.path.basename(fh.name)}"))
        elif t == "file_accept":
            pass  # phone accepted our dropped file; chunks already streaming
        elif t == "file_saved":
            self.app.ui(lambda: self.app.toast("File delivered to phone"))

    def _on_binary(self, raw):
        if not raw:
            return
        channel = raw[0]
        if channel == 0x01:  # file chunk: [0x01][8 ascii transferId][bytes]
            tid = raw[1:9].decode("ascii", "ignore")
            fh = self._inbox.get(tid)
            if fh:
                fh.write(raw[9:])
        elif channel == 0x02:  # video: [0x02][u8 flags][H.264 access unit]
            win = getattr(self.app, "win", None)
            if win:
                win.feed_video(raw[2:])

    async def _send_now(self, ws, obj):
        await ws.send(json.dumps(obj))

    async def _ready(self, ws, device):
        await self._send_now(ws, {"t": "ready"})
        self.app.ui(lambda: self.app.set_connected(True, device["name"]))
        await self._send_now(ws, {"t": "sms_list_req", "limit": 50})


VERT = Gtk.Orientation.VERTICAL
HORZ = Gtk.Orientation.HORIZONTAL


class Pill(Gtk.Box):
    """Bordered status chip with a colour dot — mirrors the mobile Pill."""

    def __init__(self, text="", tone="accent"):
        super().__init__(spacing=6, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.add_css_class("ph-pill")
        dot = Gtk.Box(valign=Gtk.Align.CENTER)
        dot.add_css_class("dot")
        self._label = Gtk.Label(label=text)
        self.append(dot)
        self.append(self._label)
        self.set(text, tone)

    def set(self, text, tone="accent"):
        self._label.set_text(text)
        for t in ("sub", "danger"):
            self.remove_css_class(t)
        if tone in ("sub", "danger"):
            self.add_css_class(tone)


def _label(text, css=None, xalign=0.0, wrap=False):
    lbl = Gtk.Label(label=text, xalign=xalign)
    if wrap:
        lbl.set_wrap(True)
    if css:
        for c in (css if isinstance(css, (list, tuple)) else [css]):
            lbl.add_css_class(c)
    return lbl


def _btn(text, cb, kind="primary"):
    b = Gtk.Button(label=text, hexpand=True)
    b.add_css_class(f"ph-{kind}")
    b.connect("clicked", lambda *_: cb())
    return b


def _card(soft=False, gap=12):
    box = Gtk.Box(orientation=VERT, spacing=gap)
    box.add_css_class("ph-soft" if soft else "ph-card")
    return box


def _stat(icon, value):
    """Small soft tile: emoji over a value (mobile Stat)."""
    box = _card(soft=True, gap=4)
    box.set_hexpand(True)
    box.set_halign(Gtk.Align.FILL)
    ico = _label(icon, xalign=0.5)
    ico.set_halign(Gtk.Align.CENTER)
    val = _label(value, "ph-title", xalign=0.5)
    val.set_halign(Gtk.Align.CENTER)
    box.append(ico)
    box.append(val)
    return box, val


class Window(Adw.ApplicationWindow):
    TABS = [("dash", "▦", "Dashboard"), ("devices", "▢", "Devices"),
            ("files", "⎙", "Files"), ("alerts", "◔", "Alerts"),
            ("kconnect", "⚯", "KDE Connect")]

    def __init__(self, app, server):
        super().__init__(application=app, title="PhoneHub")
        self.server = server
        # Roomy by default (desktop-shaped); collapses to a phone layout when
        # dragged narrow. Adw.Breakpoint swaps the nav below.
        self.set_default_size(1040, 720)
        self.set_size_request(360, 480)   # min size — lets the breakpoint collapse cleanly
        self.add_css_class("ph-root")

        self.mirror_win = None
        self._scrcpy = None              # active ScrcpyClient (adb path), or None
        self._vlock = threading.Lock()   # guards the video buffer + mirror_win
        self._vpending = []              # frames received before the viewer opens
        self._opening = False
        self._notif_rows = []
        self._connected = False
        self._peer = "Laptop"
        self._host = ""

        self.toast_overlay = Adw.ToastOverlay()
        root = Gtk.Box(orientation=VERT)
        root.add_css_class("ph-root")
        root.append(self._build_header())

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                               vexpand=True, hexpand=True)
        self.stack.add_named(self._scroll(self._build_dash()), "dash")
        self.stack.add_named(self._scroll(self._build_devices()), "devices")
        self.stack.add_named(self._scroll(self._build_files()), "files")
        self.stack.add_named(self._scroll(self._build_alerts()), "alerts")
        self.stack.add_named(self._scroll(self._build_kconnect()), "kconnect")

        # Wide: [side rail | pages].  Narrow: pages only + bottom tabbar.
        body = Gtk.Box(orientation=HORZ, vexpand=True)
        self.sidebar = self._build_sidebar()
        body.append(self.sidebar)
        body.append(self.stack)
        root.append(body)

        self.tabbar = self._build_tabbar()
        self.tabbar.set_visible(False)   # wide is the default size
        root.append(self.tabbar)

        self._select_tab("dash")
        self.toast_overlay.set_child(root)
        self.set_content(self.toast_overlay)
        self.connect("close-request", self._on_close)

        # Below 720px the side rail gives way to the mobile-style bottom tabs.
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720px"))
        bp.add_setter(self.sidebar, "visible", False)
        bp.add_setter(self.tabbar, "visible", True)
        self.add_breakpoint(bp)

    # ---- layout helpers ----
    def _scroll(self, child):
        scr = Gtk.ScrolledWindow(vexpand=True,
                                 hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=560, margin_top=14, margin_bottom=18,
                          margin_start=14, margin_end=14)
        clamp.set_child(child)
        scr.set_child(clamp)
        return scr

    def _build_header(self):
        bar = Gtk.Box(orientation=HORZ, margin_top=14, margin_bottom=10,
                      margin_start=18, margin_end=18)
        brand = Gtk.Label(xalign=0, hexpand=True)
        brand.set_markup(
            f'<span foreground="{PAL["accent"]}" weight="800">✻</span>'
            f'<span foreground="{PAL["text"]}" weight="800"> PhoneHub</span>')
        self.header_status = _label("starting…", "ph-sub", xalign=1.0)
        bar.append(brand)
        bar.append(self.header_status)
        return bar

    def _build_sidebar(self):
        rail = Gtk.Box(orientation=VERT, spacing=2)
        rail.add_css_class("ph-sidebar")
        rail.set_size_request(212, -1)
        self._side_btns = {}
        for key, icon, label in self.TABS:
            b = Gtk.Button()
            b.add_css_class("ph-side")
            inner = Gtk.Box(orientation=HORZ, spacing=12)
            ico = _label(icon, xalign=0.5); ico.add_css_class("ico")
            txt = _label(label, xalign=0); txt.add_css_class("txt"); txt.set_hexpand(True)
            inner.append(ico); inner.append(txt)
            b.set_child(inner)
            b.connect("clicked", lambda _w, k=key: self._select_tab(k))
            rail.append(b)
            self._side_btns[key] = b
        return rail

    def _build_tabbar(self):
        bar = Gtk.Box(orientation=HORZ, homogeneous=True)
        bar.add_css_class("ph-tabbar")
        self._tab_btns = {}
        for key, icon, label in self.TABS:
            b = Gtk.Button(hexpand=True)
            b.add_css_class("ph-tab")
            inner = Gtk.Box(orientation=VERT, spacing=2,
                            halign=Gtk.Align.CENTER)
            ico = _label(icon, xalign=0.5); ico.add_css_class("ico")
            txt = _label(label, xalign=0.5); txt.add_css_class("txt")
            inner.append(ico); inner.append(txt)
            b.set_child(inner)
            b.connect("clicked", lambda _w, k=key: self._select_tab(k))
            bar.append(b)
            self._tab_btns[key] = b
        return bar

    def _select_tab(self, key):
        self.stack.set_visible_child_name(key)
        for d in (getattr(self, "_tab_btns", {}), getattr(self, "_side_btns", {})):
            for k, b in d.items():
                (b.add_css_class if k == key else b.remove_css_class)("active")

    # ---- pages ----
    def _build_dash(self):
        page = Gtk.Box(orientation=VERT, spacing=14)
        card = _card(gap=12)

        head = Gtk.Box(orientation=HORZ)
        title = Gtk.Label(xalign=0, hexpand=True)
        title.set_markup(f'<span foreground="{PAL["accent"]}">✻</span> '
                         f'<span foreground="{PAL["text"]}" weight="700">PhoneHub</span>')
        self.dash_pill = Pill("Idle", "sub")
        head.append(title)
        head.append(self.dash_pill)
        card.append(head)

        # preview: a stack flipping between the pairing QR and the live state
        self.preview = Gtk.Box(orientation=VERT, spacing=10, vexpand=True,
                               halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.preview.set_size_request(-1, 320)
        wrap = Gtk.Box(orientation=VERT)
        wrap.add_css_class("ph-preview")
        self.preview_stack = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)

        # QR page
        qr_page = Gtk.Box(orientation=VERT, spacing=10, halign=Gtk.Align.CENTER,
                          valign=Gtk.Align.CENTER, vexpand=True)
        self.qr_pic = Gtk.Picture(can_shrink=False)
        self.qr_pic.set_size_request(210, 210)
        self.qr_caption = _label("Open PhoneHub on your phone and tap Scan",
                                 "ph-sub", xalign=0.5, wrap=True)
        self.qr_caption.set_justify(Gtk.Justification.CENTER)
        qr_page.append(self.qr_pic)
        qr_page.append(self.qr_caption)

        # live page
        live_page = Gtk.Box(orientation=VERT, spacing=8, halign=Gtk.Align.CENTER,
                            valign=Gtk.Align.CENTER, vexpand=True)
        self.live_icon = _label("▶", "ph-bigicon", xalign=0.5)
        self.live_text = _label("Ready to cast", "ph-sub", xalign=0.5)
        live_page.append(self.live_icon)
        live_page.append(self.live_text)

        self.preview_stack.add_named(qr_page, "qr")
        self.preview_stack.add_named(live_page, "live")
        wrap.append(self.preview_stack)
        card.append(wrap)

        # metrics
        mrow = Gtk.Box(orientation=HORZ, spacing=10, margin_top=4, margin_bottom=4)
        for lab, attr in (("LATENCY", "_lat"), ("BITRATE", "_bit")):
            col = Gtk.Box(orientation=VERT, spacing=2, hexpand=True)
            col.append(_label(lab, "ph-faint"))
            val = _label("—", "ph-metricval")
            setattr(self, attr, val)
            col.append(val)
            mrow.append(col)
        card.append(mrow)

        self.mirror_btn = _btn("⇲  Start Mirroring", self.toggle_mirror, "primary")
        card.append(self.mirror_btn)
        page.append(card)
        return page

    def _build_devices(self):
        page = Gtk.Box(orientation=VERT, spacing=14)
        card = _card(gap=14)

        head = Gtk.Box(orientation=HORZ)
        head.append(_label("Active Link", "ph-title", xalign=0))
        spacer = Gtk.Box(hexpand=True); head.append(spacer)
        self.dev_pill = Pill("OFFLINE", "sub")
        head.append(self.dev_pill)
        card.append(head)

        dev = _card(soft=True, gap=12)
        top = Gtk.Box(orientation=HORZ, spacing=12)
        top.append(_label("📱", xalign=0))
        col = Gtk.Box(orientation=VERT, hexpand=True)
        self.dev_name = _label("No device", "ph-title", xalign=0)
        col.append(self.dev_name)
        col.append(_label("Primary link · v0.1", "ph-sub", xalign=0))
        top.append(col)
        self.dev_pill2 = Pill("OFFLINE", "sub")
        top.append(self.dev_pill2)
        dev.append(top)

        stats = Gtk.Box(orientation=HORZ, spacing=10)
        bat, self.bat_val = _stat("🔋", "—")
        sig, self.sig_val = _stat("📶", "—")
        sto, _ = _stat("🖴", "—")
        for w in (bat, sig, sto):
            stats.append(w)
        dev.append(stats)

        actions = Gtk.Box(orientation=HORZ, spacing=10)
        actions.append(_btn("Mirror Screen", self.toggle_mirror, "primary"))
        ring = Gtk.Button(label="⟳"); ring.add_css_class("ph-iconbtn")
        ring.connect("clicked", lambda *_: self.server.send({"t": "ring"}))
        actions.append(ring)
        dev.append(actions)
        card.append(dev)

        card.append(_label("Paired History", "ph-faint"))
        peers = getattr(self.server, "peers", {}) or {}
        if peers:
            for info in list(peers.values())[:6]:
                card.append(self._hist_row("📱", info.get("name", "Phone"), "Paired"))
        else:
            card.append(_label("No paired devices yet", "ph-sub", xalign=0))
        page.append(card)
        return page

    def _hist_row(self, icon, title, sub):
        row = Gtk.Box(orientation=HORZ, spacing=12, margin_top=2, margin_bottom=2)
        ic = _label(icon, xalign=0)
        col = Gtk.Box(orientation=VERT, hexpand=True)
        col.append(_label(title, "ph-title", xalign=0))
        col.append(_label(sub, "ph-sub", xalign=0))
        row.append(ic)
        row.append(col)
        row.append(_label("›", "ph-sub"))
        return row

    def _build_files(self):
        page = Gtk.Box(orientation=VERT, spacing=14)
        card = _card(gap=14)
        title = Gtk.Label(xalign=0)
        title.set_markup(f'<span foreground="{PAL["accent"]}">✻</span> '
                         f'<span foreground="{PAL["text"]}" weight="700">Files</span>')
        card.append(title)

        link = _card(soft=True, gap=2)
        lrow = Gtk.Box(orientation=HORZ, spacing=10)
        lcol = Gtk.Box(orientation=VERT, hexpand=True)
        lcol.append(_label("Precision Link", "ph-title", xalign=0))
        self.files_link = _label("Waiting for phone…", "ph-sub", xalign=0)
        lcol.append(self.files_link)
        lrow.append(lcol)
        clip = Gtk.Button(label="Send Clipboard")
        clip.add_css_class("ph-ghost")
        clip.connect("clicked", lambda *_: self.send_clip())
        lrow.append(clip)
        link.append(lrow)
        card.append(link)

        send = _btn("📤   Send a File", self.send_file, "primary")
        card.append(send)

        sb = Gtk.Box(orientation=VERT, spacing=4, halign=Gtk.Align.CENTER)
        sb.add_css_class("ph-sendbox")
        sb.append(_label("📤", xalign=0.5))
        sb.append(_label("Drop a file here", "ph-title", xalign=0.5))
        sb.append(_label("or use the button above", "ph-sub", xalign=0.5))
        card.append(sb)

        card.append(_label("Recent Transfers", "ph-faint"))
        self.files_recent = _label("No transfers yet", "ph-sub", xalign=0)
        card.append(self.files_recent)
        page.append(card)
        return page

    def _build_alerts(self):
        page = Gtk.Box(orientation=VERT, spacing=14)
        card = _card(gap=14)
        title = Gtk.Label(xalign=0)
        title.set_markup(f'<span foreground="{PAL["accent"]}">✻</span> '
                         f'<span foreground="{PAL["text"]}" weight="700">Alerts</span>')
        card.append(title)

        link = _card(soft=True, gap=2)
        lrow = Gtk.Box(orientation=HORZ, spacing=10)
        lrow.append(_label("🔗", xalign=0))
        lcol = Gtk.Box(orientation=VERT, hexpand=True)
        self.alert_state = _label("DISCONNECTED", "ph-accent", xalign=0)
        lcol.append(self.alert_state)
        lcol.append(_label("Phone link", "ph-title", xalign=0))
        lrow.append(lcol)
        link.append(lrow)
        card.append(link)

        card.append(_label("Phone Notifications", "ph-faint"))
        self.notif_box = Gtk.Box(orientation=VERT, spacing=8)
        self.notif_empty = _label("No notifications yet", "ph-sub", xalign=0)
        self.notif_box.append(self.notif_empty)
        card.append(self.notif_box)
        page.append(card)
        return page

    def _build_kconnect(self):
        page = Gtk.Box(orientation=VERT, spacing=14)
        card = _card(gap=14)

        head = Gtk.Box(orientation=HORZ)
        title = Gtk.Label(xalign=0, hexpand=True)
        title.set_markup(f'<span foreground="{PAL["accent"]}">⚯</span> '
                         f'<span foreground="{PAL["text"]}" weight="700">KDE Connect</span>')
        head.append(title)
        self.kc_pill = Pill("—", "sub")
        head.append(self.kc_pill)
        card.append(head)

        if not KdeConnect.available():
            card.append(_label("KDE Connect is not installed on this system.",
                               "ph-sub", xalign=0, wrap=True))
            page.append(card)
            return page

        card.append(_label("Drives the system KDE Connect daemon. Pair your phone "
                           "in the KDE Connect Android app first.", "ph-sub",
                           xalign=0, wrap=True))

        # device picker
        self.kc_combo = Gtk.DropDown.new_from_strings(["(no devices)"])
        self.kc_devices = []   # parallel list of (id, name)
        card.append(self.kc_combo)

        row1 = Gtk.Box(orientation=HORZ, spacing=10)
        row1.append(_btn("⟳  Refresh", self._kc_refresh, "ghost"))
        row1.append(_btn("Pair", lambda: self._kc_action("pair"), "ghost"))
        row1.append(_btn("Ring", lambda: self._kc_action("ring"), "primary"))
        card.append(row1)

        row2 = Gtk.Box(orientation=HORZ, spacing=10)
        row2.append(_btn("📋  Clipboard", lambda: self._kc_action("clipboard"), "ghost"))
        row2.append(_btn("📤  Share File", lambda: self._kc_action("share"), "ghost"))
        row2.append(_btn("Ping", lambda: self._kc_action("ping"), "ghost"))
        card.append(row2)

        self.kc_status = _label("", "ph-sub", xalign=0, wrap=True)
        card.append(self.kc_status)

        page.append(card)
        GLib.idle_add(self._kc_refresh)   # populate once the UI is up
        return page

    def _kc_selected(self):
        if not self.kc_devices:
            return None
        i = self.kc_combo.get_selected()
        if i is None or i < 0 or i >= len(self.kc_devices):
            i = 0
        return self.kc_devices[i]

    def _kc_refresh(self):
        # subprocess calls block for seconds — do them off the UI thread.
        self.kc_status.set_text("Scanning…")
        threading.Thread(target=self._kc_refresh_worker, daemon=True).start()
        return False

    def _kc_refresh_worker(self):
        KdeConnect.refresh()
        reachable = KdeConnect.devices(available_only=True)
        devs = reachable or KdeConnect.devices(available_only=False)
        bat = KdeConnect.battery(devs[0][0]) if devs else None

        def apply():
            self.kc_devices = devs
            names = [n for (_i, n) in devs] or ["(no devices)"]
            self.kc_combo.set_model(Gtk.StringList.new(names))
            self.kc_pill.set("Reachable" if reachable else ("Known" if devs else "None"),
                             "accent" if reachable else "sub")
            if devs:
                self.kc_status.set_text(f"{len(devs)} device(s)" +
                                        (f" · battery {bat}%" if bat is not None else ""))
            else:
                self.kc_status.set_text("No devices — open KDE Connect on your phone, same network.")
            return False
        GLib.idle_add(apply)

    def _kc_action(self, what):
        dev = self._kc_selected()
        if not dev:
            self.toast("No KDE Connect device — Refresh first")
            return
        dev_id, name = dev
        if what == "share":
            Gtk.FileDialog(title="Share via KDE Connect").open(
                self, None, lambda dlg, res: self._kc_share_ready(dlg, res, dev_id, name))
            return

        fn = {"clipboard": KdeConnect.send_clipboard, "ring": KdeConnect.ring,
              "ping": KdeConnect.ping, "pair": KdeConnect.pair}.get(what)
        if not fn:
            return
        self.kc_status.set_text(f"{what}…")

        def worker():
            ok, msg = fn(dev_id)

            def apply():
                self.toast(f"KDE Connect · {name}: {'✓' if ok else '✗'} {what}")
                self.kc_status.set_text(msg or f"{what} sent")
                if what == "pair":
                    self._kc_refresh()
                return False
            GLib.idle_add(apply)
        threading.Thread(target=worker, daemon=True).start()

    def _kc_share_ready(self, dialog, res, dev_id, name):
        try:
            f = dialog.open_finish(res)
        except Exception:
            return
        path = f.get_path() if f else None
        if path:
            ok, msg = KdeConnect.share_file(dev_id, path)
            self.toast(f"KDE Connect · {name}: {'✓ shared' if ok else '✗ ' + msg}")

    # ---- UI updates (always on main thread) ----
    def set_status(self, text):
        self.header_status.set_text(text)

    def show_qr(self, path, pin, host):
        self._host = host
        self.qr_pic.set_filename(path)
        self.qr_caption.set_text(f"Scan with PhoneHub\n{host}:{PORT}  ·  PIN {pin}")
        self.preview_stack.set_visible_child_name("qr")
        self.set_status(f"Ready on {host}:{PORT}")

    def set_connected(self, connected, name):
        self._connected = connected
        if connected:
            self._peer = name
            self.dash_pill.set("Connected", "accent")
            self.dev_pill.set("SECURE", "accent")
            self.dev_pill2.set("ONLINE", "accent")
            self.dev_name.set_text(name)
            self.files_link.set_text("Connected to phone")
            self.alert_state.set_text("CONNECTED")
            self.live_icon.set_text("◉")
            self.live_text.set_text(f"Connected to {name}")
            self.preview_stack.set_visible_child_name("live")
            self.set_status(f"✅ {name}")
        else:
            self.dash_pill.set("Idle", "sub")
            self.dev_pill.set("OFFLINE", "sub")
            self.dev_pill2.set("OFFLINE", "sub")
            self.dev_name.set_text("No device")
            self.files_link.set_text("Waiting for phone…")
            self.alert_state.set_text("DISCONNECTED")
            self.sig_val.set_text("—")
            self.preview_stack.set_visible_child_name("qr")
            self.set_status(name)

    def set_battery(self, level, charging):
        if level is not None:
            self.bat_val.set_text(f"{level}%{' ⚡' if charging else ''}")

    def add_notification(self, msg):
        if self.notif_empty:
            self.notif_box.remove(self.notif_empty)
            self.notif_empty = None
        row = _card(soft=True, gap=2)
        row.append(_label(f"{msg.get('app','')} · {msg.get('title','')}".strip(" ·"),
                          "ph-title", xalign=0, wrap=True))
        sub = msg.get("text", "")
        if sub:
            row.append(_label(sub, "ph-sub", xalign=0, wrap=True))
        self.notif_box.prepend(row)
        self._notif_rows.insert(0, row)
        if len(self._notif_rows) > 12:
            self.notif_box.remove(self._notif_rows.pop())

    def recv_clipboard(self, text):
        self.get_clipboard().set(text)
        self.toast("Clipboard received from phone")

    def show_sms(self, threads):
        pass  # phase: dedicated Messages window

    def toast(self, m):
        self.toast_overlay.add_toast(Adw.Toast(title=GLib.markup_escape_text(str(m)), timeout=3))

    # ---- actions ----
    def feed_video(self, data):
        """Server-thread entry for video frames. Push to the live viewer, or
        buffer until it opens — never drop the leading frames, because the first
        one carries the SPS/PPS the H.264 decoder needs (sent only once)."""
        with self._vlock:
            if self.mirror_win:
                self.mirror_win.push(data)
                return
            self._vpending.append(data)
            if len(self._vpending) > 600:   # cap (~ a few seconds) so it can't grow unbounded
                self._vpending.pop(0)
            open_now = not self._opening
            self._opening = True
        if open_now:
            GLib.idle_add(self.ensure_mirror)   # open the viewer on the UI thread

    def ensure_mirror(self):
        """Open the mirror viewer if not already open, then flush any frames
        buffered while it was opening (in order, before going live)."""
        if self.mirror_win:
            return False
        mw = MirrorWindow(on_close=self._mirror_closed, on_input=self.server.send)
        mw.set_transient_for(self)
        mw.present()
        with self._vlock:
            pending, self._vpending = self._vpending, []
            for d in pending:
                mw.push(d)
            self.mirror_win = mw
            self._opening = False
        return False  # for GLib.idle_add

    # ---- scrcpy-backed mirror (bundled server + our GStreamer viewer) ----
    # We run scrcpy's server on the phone and speak its protocol ourselves
    # (scrcpy_client.py): video → the GStreamer MirrorWindow, mouse/keyboard →
    # scrcpy control. No external scrcpy binary, no snap.
    SCRCPY_JAR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", "vendor", "scrcpy-server.jar")

    @staticmethod
    def _adb_serial():
        """Serial of the one connected adb device, or None."""
        try:
            out = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=5).stdout
        except Exception:
            return None
        devs = [ln.split("\t")[0] for ln in out.splitlines()[1:]
                if ln.strip() and ln.strip().endswith("device")]
        return devs[0] if devs else None

    def toggle_mirror(self):
        if self._scrcpy or self.mirror_win:
            self.stop_mirror()
            self.toast("Mirror stopped")
        else:
            self.start_mirror()

    def start_mirror(self):
        """Auto-pick the transport: bundled scrcpy over adb when a cable's
        present (best quality), else PhoneHub's own WebSocket mirror over the
        paired Wi-Fi/Tailscale link."""
        if self._scrcpy or self.mirror_win:
            self.toast("Mirror already running")
            return

        serial = self._adb_serial()
        if serial and os.path.exists(self.SCRCPY_JAR):
            self._start_scrcpy(serial)
        elif self._connected:
            self._start_ws_mirror()
        else:
            self.toast("Plug in USB for best quality, or pair the phone over Wi-Fi first")

    # --- path A: bundled scrcpy over adb ---
    def _start_scrcpy(self, serial):
        self._mirror_serial = serial
        self.mirror_win = MirrorWindow(on_close=self._mirror_closed,
                                       on_input=self._scrcpy_input,
                                       on_drop=self._push_files)
        self.mirror_win.set_transient_for(self)
        self.mirror_win.present()

        from scrcpy_client import ScrcpyClient
        self._scrcpy = ScrcpyClient(
            self.SCRCPY_JAR,
            on_frame=self._scrcpy_frame,
            on_size=lambda w, h: None,
            on_stop=lambda: GLib.idle_add(self._scrcpy_stopped),
            serial=serial, max_size=1200, bitrate=8_000_000, max_fps=60,
        )
        try:
            self._scrcpy.start()
        except Exception as e:
            self.toast(f"scrcpy failed: {e}")
            self._scrcpy = None
            if self.mirror_win:
                self.mirror_win.destroy()
                self.mirror_win = None
            return

        self._set_mirroring(True)
        self.toast("Mirroring (scrcpy / USB) — control with mouse & keyboard")

    def _scrcpy_frame(self, data):
        # called from the scrcpy video thread; appsrc push-buffer is thread-safe
        mw = self.mirror_win
        if mw:
            mw.push(data)

    def _scrcpy_input(self, msg):
        """Translate MirrorWindow's normalised input events into scrcpy control."""
        sc = self._scrcpy
        if not sc:
            return
        kind = msg.get("kind")
        if kind == "touch":
            from scrcpy_client import AMOTION_DOWN, AMOTION_UP, AMOTION_MOVE
            action = {"down": AMOTION_DOWN, "up": AMOTION_UP,
                      "move": AMOTION_MOVE}.get(msg.get("action"))
            if action is not None:
                sc.inject_touch(action, msg.get("x", 0), msg.get("y", 0))
        elif kind == "swipe":
            sc.inject_scroll(0.5, 0.5, msg.get("dx", 0.0), -msg.get("dy", 0.0))
        elif kind == "key":
            sc.key_press(msg.get("key", ""))
        elif kind == "text":
            sc.inject_text(msg.get("text", ""))

    def _scrcpy_stopped(self):
        """scrcpy stream ended (phone unplugged, server died)."""
        self._scrcpy = None
        if self.mirror_win:
            self.mirror_win.destroy()
            self.mirror_win = None
        self._set_mirroring(False)
        return False

    # --- drag-drop: laptop file → phone ---
    def _push_files(self, paths):
        """Files dropped on the mirror window. Over USB use adb push (lands in
        the phone's Downloads); over Wi-Fi stream through the WebSocket."""
        serial = getattr(self, "_mirror_serial", None)
        if serial:
            def worker():
                for p in paths:
                    try:
                        subprocess.run(["adb", "-s", serial, "push", p, "/sdcard/Download/"],
                                       capture_output=True, text=True, timeout=120)
                    except Exception:
                        pass
                GLib.idle_add(lambda: self.toast(f"Sent {len(paths)} file(s) to the phone"))
            threading.Thread(target=worker, daemon=True).start()
        else:
            for p in paths:
                self.server.push_file(p)
            self.toast(f"Sending {len(paths)} file(s) to the phone…")

    # --- path B: PhoneHub's own WebSocket mirror (phone app over Wi-Fi/Tailscale) ---
    def _start_ws_mirror(self):
        # Input goes back to the phone as {"t":"input",...}; its InputService
        # injects it. Video arrives as binary 0x02 → feed_video → this window.
        self._mirror_serial = None
        self.mirror_win = MirrorWindow(on_close=self._mirror_closed,
                                       on_input=self.server.send,
                                       on_drop=self._push_files)
        self.mirror_win.set_transient_for(self)
        self.mirror_win.present()
        self.server.send({"t": "mirror_start", "maxW": 1080, "bitrate": 8_000_000})
        self._set_mirroring(True)
        self.toast("Mirroring (Wi-Fi) — accept the screen-capture prompt on the phone")

    # --- shared teardown ---
    def stop_mirror(self):
        sc, self._scrcpy = self._scrcpy, None
        if sc:
            try:
                sc.stop()
            except Exception:
                pass
        else:
            self.server.send({"t": "mirror_stop"})   # harmless if no phone link
        if self.mirror_win:
            self.mirror_win.destroy()
            self.mirror_win = None
        self._set_mirroring(False)

    def _on_close(self, *_):
        self.stop_mirror()   # don't leave scrcpy/sockets running after exit
        return False

    def _set_mirroring(self, on):
        self.mirror_btn.set_label("◉  Stop Mirroring" if on else "⇲  Start Mirroring")
        self.mirror_btn.remove_css_class("ph-primary" if on else "ph-danger")
        self.mirror_btn.add_css_class("ph-danger" if on else "ph-primary")
        if on:
            self.dash_pill.set("Mirroring", "accent")
            self.live_icon.set_text("◉")
            self.live_text.set_text("Your screen is streaming")
            self.live_text.remove_css_class("ph-sub")
            self.live_text.add_css_class("ph-accent")
            self.preview_stack.set_visible_child_name("live")
        else:
            self.dash_pill.set("Connected" if self._connected else "Idle",
                               "accent" if self._connected else "sub")
            self._lat.set_text("—"); self._bit.set_text("—")
            self.live_text.add_css_class("ph-sub")

    def _mirror_closed(self):
        # The viewer window is closing itself — drop our ref (don't re-destroy)
        # and tear down whichever transport is live.
        self.mirror_win = None
        sc, self._scrcpy = self._scrcpy, None
        if sc:
            try:
                sc.stop()
            except Exception:
                pass
        else:
            self.server.send({"t": "mirror_stop"})
        self._set_mirroring(False)

    def send_clip(self):
        self.get_clipboard().read_text_async(None, self._clip_ready)

    def _clip_ready(self, clipboard, res):
        try:
            text = clipboard.read_text_finish(res)
        except Exception:
            text = None
        if text:
            self.server.send({"t": "clipboard", "text": text})
            self.toast("Sent clipboard to phone")
        else:
            self.toast("Clipboard empty")

    def send_file(self):
        Gtk.FileDialog(title="Send to phone").open(self, None, self._file_ready)

    def _file_ready(self, dialog, res):
        try:
            f = dialog.open_finish(res)
        except Exception:
            return
        path = f.get_path()
        if path:
            # the desktop->phone push is handled by the server thread
            self.server.send({"t": "file_offer",
                              "transferId": secrets.token_hex(4),
                              "name": os.path.basename(path),
                              "size": os.path.getsize(path)})
            self.toast("File offered (transfer wiring lands with the Android app)")


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.server = Server(self)
        self.win = None

    def do_activate(self):
        if not self.win:
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            install_css()
            self.win = Window(self, self.server)
            self.server.start()
        self.win.present()

    # helper so server thread can touch the UI safely
    def ui(self, fn):
        GLib.idle_add(fn)

    # convenience pass-throughs used by Server
    def set_status(self, t): self.win and self.win.set_status(t)
    def show_qr(self, path, pin, host): self.win and self.win.show_qr(path, pin, host)
    def set_connected(self, c, n): self.win and self.win.set_connected(c, n)
    def set_battery(self, l, c): self.win and self.win.set_battery(l, c)
    def add_notification(self, m): self.win and self.win.add_notification(m)
    def recv_clipboard(self, t): self.win and self.win.recv_clipboard(t)
    def show_sms(self, th): self.win and self.win.show_sms(th)
    def toast(self, m): self.win and self.win.toast(m)


if __name__ == "__main__":
    App().run(None)
