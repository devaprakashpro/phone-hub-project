"""
Desktop-side screen mirror: decode the H.264 stream the phone sends (binary
channel 0x02) and paint it into a GTK4 window.

Pipeline:  appsrc -> h264parse -> avdec_h264 -> videoconvert(RGBA) -> appsink
Each decoded frame becomes a GdkMemoryTexture shown in a Gtk.Picture. We use
appsink (not gtk4paintablesink) so there's no dependency on gst-plugins-rs.
"""
import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gst", "1.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gst, Gdk, GLib

Gst.init(None)


class MirrorWindow(Gtk.Window):
    def __init__(self, on_close=None, on_input=None, on_drop=None):
        super().__init__(title="Phone")
        self.set_default_size(360, 760)
        self.on_close = on_close
        self.on_input = on_input
        self.on_drop = on_drop

        self.picture = Gtk.Picture()
        self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.picture.set_vexpand(True)

        # Layout: live screen on top, a small control bar underneath.
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self.picture)
        box.append(self._build_controls())
        self.set_child(box)

        # Mouse → touch. down/move/up are forwarded so drags & flings feel native.
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.picture.add_controller(drag)

        # Wheel → scroll gesture on the phone.
        scroll = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.BOTH_AXES)
        scroll.connect("scroll", self._scroll)
        self.picture.add_controller(scroll)

        # Keyboard → typing + navigation keys.
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key_pressed)
        self.add_controller(keys)

        # Drag a file from the laptop and drop it on the phone window → transfer.
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_file_drop)
        self.add_controller(drop)

        self.connect("close-request", self._closed)
        self._build_pipeline()

    def _on_file_drop(self, target, value, x, y):
        try:
            files = value.get_files()        # Gdk.FileList → [Gio.File, ...]
        except Exception:
            return False
        paths = [f.get_path() for f in files if f.get_path()]
        if paths and self.on_drop:
            self.on_drop(paths)
            return True
        return False

    def _build_controls(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                      margin_top=8, margin_bottom=8, margin_start=8, margin_end=8,
                      homogeneous=True)
        for label, key in (("◀  Back", "BACK"), ("⊙  Home", "HOME"),
                           ("▢  Recents", "RECENTS")):
            b = Gtk.Button(label=label, hexpand=True)
            b.add_css_class("ph-ghost")
            b.connect("clicked", lambda _w, k=key: self._send_key(k))
            bar.append(b)
        return bar

    def _build_pipeline(self):
        self.pipeline = Gst.parse_launch(
            "appsrc name=src is-live=true do-timestamp=true format=time "
            'caps=video/x-h264,stream-format=byte-stream,alignment=au '
            "! h264parse ! avdec_h264 ! videoconvert "
            "! video/x-raw,format=RGBA ! appsink name=sink emit-signals=true "
            "max-buffers=2 drop=true sync=false"
        )
        self.appsrc = self.pipeline.get_by_name("src")
        sink = self.pipeline.get_by_name("sink")
        sink.connect("new-sample", self._on_sample)

        # Bus watch — without this a decode error stalls the pipeline silently.
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_bus_error)
        bus.connect("message::warning", self._on_bus_warn)

        self._pushed = 0
        self._rendered = 0
        self.pipeline.set_state(Gst.State.PLAYING)

    def _on_bus_error(self, bus, msg):
        err, dbg = msg.parse_error()
        print(f"[mirror] GST ERROR: {err.message} | {dbg}", file=sys.stderr, flush=True)

    def _on_bus_warn(self, bus, msg):
        err, dbg = msg.parse_warning()
        print(f"[mirror] GST WARN: {err.message}", file=sys.stderr, flush=True)

    def push(self, data: bytes):
        """Feed an H.264 access unit (called from the network thread)."""
        buf = Gst.Buffer.new_wrapped(data)
        ret = self.appsrc.emit("push-buffer", buf)
        self._pushed += 1
        if self._pushed <= 3 or self._pushed % 30 == 0:
            print(f"[mirror] pushed#{self._pushed} bytes={len(data)} ret={ret} rendered={self._rendered}",
                  file=sys.stderr, flush=True)

    def _on_sample(self, sink):
        sample = sink.emit("pull-sample")
        if not sample:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        caps = sample.get_caps().get_structure(0)
        w = caps.get_value("width")
        h = caps.get_value("height")
        ok, minfo = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        data = bytes(minfo.data)
        buf.unmap(minfo)
        gbytes = GLib.Bytes.new(data)
        self._rendered += 1
        if self._rendered <= 3 or self._rendered % 30 == 0:
            print(f"[mirror] rendered#{self._rendered} {w}x{h}", file=sys.stderr, flush=True)

        def paint():
            tex = Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.R8G8B8A8, gbytes, w * 4)
            self.picture.set_paintable(tex)
            return False
        GLib.idle_add(paint)
        return Gst.FlowReturn.OK

    # ---- input forwarding (normalized 0..1) ----
    def _norm(self, x, y):
        a = self.picture.get_allocation()
        w = a.width or 1
        h = a.height or 1
        return (max(0.0, min(1.0, x / w)), max(0.0, min(1.0, y / h)))

    def _touch(self, action, x, y):
        if self.on_input:
            nx, ny = self._norm(x, y)
            self.on_input({"t": "input", "kind": "touch", "action": action, "x": nx, "y": ny})

    def _send_key(self, key):
        if self.on_input:
            self.on_input({"t": "input", "kind": "key", "key": key})

    # mouse: down at press, move while dragging, up at release (native drags)
    def _drag_begin(self, g, x, y):
        self._drag_start = (x, y)
        self._touch("down", x, y)

    def _drag_update(self, g, off_x, off_y):
        sx, sy = getattr(self, "_drag_start", (0, 0))
        self._touch("move", sx + off_x, sy + off_y)

    def _drag_end(self, g, off_x, off_y):
        sx, sy = getattr(self, "_drag_start", (0, 0))
        self._touch("up", sx + off_x, sy + off_y)

    # wheel: forward as a scroll swipe (fraction of the screen per notch)
    def _scroll(self, controller, dx, dy):
        if self.on_input:
            self.on_input({"t": "input", "kind": "swipe",
                           "dx": dx * 0.18, "dy": dy * 0.30})
        return True

    # keyboard: navigation keys + unicode typing
    def _key_pressed(self, controller, keyval, keycode, state):
        if not self.on_input:
            return False
        named = {
            Gdk.KEY_Escape: "BACK",
            Gdk.KEY_Return: "ENTER",
            Gdk.KEY_KP_Enter: "ENTER",
            Gdk.KEY_BackSpace: "DEL",
            Gdk.KEY_Delete: "DEL",
        }.get(keyval)
        if named:
            self._send_key(named)
            return True
        uni = Gdk.keyval_to_unicode(keyval)
        if uni >= 32:  # printable character
            self.on_input({"t": "input", "kind": "text", "text": chr(uni)})
            return True
        return False

    def _closed(self, *_):
        try:
            self.pipeline.set_state(Gst.State.NULL)
        except Exception:
            pass
        if self.on_close:
            self.on_close()
        return False
