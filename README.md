# PhoneHub — your own phone↔laptop ecosystem

A self-contained, two-piece app that does what Apple Continuity does, built from
scratch — **no KDE Connect, no scrcpy**. A desktop app and an Android companion
talk directly over your LAN.

```
┌─────────────────┐        WebSocket (LAN, :8766)        ┌──────────────────┐
│  PhoneHub        │  ◀───────  JSON control  ─────────▶ │  PhoneHub         │
│  (Linux, GTK4)   │  ◀───────  binary file/video ─────▶ │  Companion        │
│  server + UI     │                                      │  (Android/Kotlin) │
└─────────────────┘                                      └──────────────────┘
```

## Features (all in the one project)
| Feature | Desktop | Android | Status |
|---|---|---|---|
| Pairing (PIN) | ✅ | scaffold | **Phase 1 done** |
| Battery display | ✅ | scaffold | Phase 1/2 |
| Clipboard sync | ✅ | scaffold | Phase 1/2 |
| File transfer | ✅ recv | scaffold | Phase 2 |
| Notifications mirror | ✅ list | NotificationListenerService | Phase 2 |
| SMS read/reply | UI stub | SMS APIs | Phase 3 |
| **Screen mirror + control** | GStreamer decode | MediaProjection→MediaCodec H.264 | Phase 4 (hardest) |
| Calls | alert via notif | + Bluetooth HFP for audio | Phase 5 |

## Phases / roadmap
1. **✅ Desktop server + protocol + UI** — runnable now.
2. **Android core** — foreground service, WebSocket client, pairing, battery, clipboard.
3. **File transfer + notifications mirror** end-to-end.
4. **Screen mirror**: MediaProjection → MediaCodec (H.264) → binary frames →
   desktop `appsrc ! h264parse ! avdec_h264 ! gtk4paintablesink`. Then input
   injection back (touch/keys) for control. *Requires on-device iteration.*
5. **Calls**: notify + route audio over Bluetooth hands-free.

## Run the desktop app today
```bash
cd desktop
python3 phonehub_desktop.py     # needs python3-gi, gir Gtk4/Adw, python3-websockets
```
It shows a **pairing PIN** when a phone connects and listens on `:8766`. The
window is desktop-shaped (side-rail nav) and collapses to the phone layout
(bottom tabs) when narrowed.

## Connecting the phone — wireless vs USB
The phone races two routes at once: the scanned LAN/Tailscale IP (**wireless**)
and `127.0.0.1:8766` (**USB**). Wireless works as soon as both are on the same
network. For USB you must forward the port first (Metro only reverses 8081):
```bash
scripts/usb-link.sh        # adb reverse tcp:8766 tcp:8766, re-run after replugging
```
Without that, pairing only succeeds wirelessly.

## Build the Android app (Phase 2+)
You don't have the Android SDK yet. Run:
```bash
scripts/install-android-sdk.sh        # installs cmdline-tools + platform + build-tools
```
or install **Android Studio** (recommended — bundles SDK + Gradle + emulator):
```bash
sudo snap install android-studio --classic
```
Then open `android/` in Android Studio and Run.

## Layout
```
desktop/   GTK4 server app (Python)          ← works now
android/   Kotlin/Compose companion app      ← Phase 2+
docs/      PROTOCOL.md (wire format)
scripts/   toolchain installer
```
