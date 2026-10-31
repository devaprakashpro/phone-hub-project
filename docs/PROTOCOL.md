# PhoneHub wire protocol (v0)

A self-contained protocol between the **desktop** (server) and the **Android
companion** (client). No KDE Connect, no scrcpy — our own thing.

## Transport
- **WebSocket** over TCP. Desktop runs the server on `:8766`.
- Discovery: desktop advertises `_phonehub._tcp` via mDNS/Zeroconf (phase 2).
  Until then the phone connects by typing the desktop's LAN IP.
- Pairing: desktop shows a **6-digit PIN**. Phone sends it in `auth`. On match,
  the desktop stores the phone's `deviceId` + a generated token in
  `~/.config/phonehub/peers.json` so future connects skip the PIN.
- (Phase 3) wrap in TLS with a self-signed cert pinned at pairing time.

## Framing
Two kinds of WebSocket frames:
- **Text frames** = JSON control messages, shape `{ "t": "<type>", ... }`.
- **Binary frames** = bulk payloads (file chunks, video NAL units), prefixed
  with a 1-byte channel id:
  - `0x01` file chunk  → `[0x01][u32 transferId][bytes...]`
  - `0x02` video frame → `[0x02][u8 flags][H.264 Annex-B NAL units...]`
    flag bit0 = keyframe.

## Control messages

### Handshake
```
phone → pc : {"t":"hello","deviceId":"...","name":"Pixel 8","token":"<if paired>"}
pc → phone : {"t":"need_pin"}                       # not paired yet
phone → pc : {"t":"auth","pin":"482913"}
pc → phone : {"t":"paired","token":"<opaque>"}      # or {"t":"auth_fail"}
pc → phone : {"t":"ready"}
```

### Telemetry (phone → pc, pushed on change)
```
{"t":"battery","level":74,"charging":true}
{"t":"notification","id":"...","app":"WhatsApp","title":"Mom","text":"call me","ts":...}
{"t":"notif_removed","id":"..."}
```

### Clipboard (bidirectional)
```
{"t":"clipboard","text":"..."}
```

### SMS
```
pc → phone : {"t":"sms_list_req","limit":50}
phone → pc : {"t":"sms_list","threads":[{"addr":"+91...","name":"Mom","snippet":"...","ts":...}]}
pc → phone : {"t":"sms_thread_req","addr":"+91..."}
phone → pc : {"t":"sms_thread","addr":"+91...","msgs":[{"body":"...","ts":...,"out":false}]}
pc → phone : {"t":"sms_send","addr":"+91...","body":"..."}
```

### Files
```
sender → recv : {"t":"file_offer","transferId":"t1","name":"a.jpg","size":12345,"mime":"image/jpeg"}
recv  → sender: {"t":"file_accept","transferId":"t1"}   # or file_reject
sender → recv : <binary 0x01 chunks...>
sender → recv : {"t":"file_done","transferId":"t1"}
```

### Find / ring
```
pc → phone : {"t":"ring"}
```

### Mirror + control (phase 2)
```
pc → phone : {"t":"mirror_start","maxW":1080,"bitrate":8000000,"screenOff":true}
phone → pc : {"t":"mirror_meta","w":1080,"h":2400,"codec":"h264"}
phone → pc : <binary 0x02 video frames...>
pc → phone : {"t":"input","kind":"touch","action":"down","x":0.5,"y":0.4}  # x,y normalised 0..1
pc → phone : {"t":"input","kind":"touch","action":"up","x":0.5,"y":0.4}    # down→up far apart = swipe
pc → phone : {"t":"input","kind":"swipe","dx":0.0,"dy":0.3}                # wheel scroll (fraction of screen)
pc → phone : {"t":"input","kind":"key","key":"BACK"}    # BACK|HOME|RECENTS|NOTIFICATIONS|ENTER|DEL
pc → phone : {"t":"input","kind":"text","text":"hello"} # append to focused field
pc → phone : {"t":"mirror_stop"}
```

Input injection on the phone uses an **AccessibilityService** (taps/swipes via
`dispatchGesture`, navigation via global actions, typing via the focused node).
Notification mirroring uses a **NotificationListenerService**. Both are optional
powers the user enables once in system settings.
