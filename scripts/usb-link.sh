#!/usr/bin/env bash
# Make the USB (wired) transport work.
#
# The phone always races two routes to the desktop: the scanned LAN IP
# (Wi-Fi / Tailscale = "wireless") and 127.0.0.1:8766 (the USB tunnel). The
# loopback route only reaches the desktop if adb is forwarding the port —
# Metro auto-reverses 8081 but never the PhoneHub port, so without this the
# phone could *only* pair wirelessly.
#
# Run this once per USB session (re-run if you replug the cable):
#   scripts/usb-link.sh
set -euo pipefail

PORT="${PHONEHUB_PORT:-8766}"

if ! command -v adb >/dev/null 2>&1; then
  echo "adb not found. Install platform-tools (scripts/install-android-sdk.sh) or 'sudo apt install adb'." >&2
  exit 1
fi

devices=$(adb devices | awk 'NR>1 && $2=="device"{print $1}')
if [ -z "$devices" ]; then
  echo "No USB device in 'device' state. Plug the phone in and accept the USB-debugging prompt." >&2
  exit 1
fi

for serial in $devices; do
  adb -s "$serial" reverse "tcp:$PORT" "tcp:$PORT"
  echo "✓ $serial → 127.0.0.1:$PORT now reaches this desktop"
done

echo "USB link ready. Open PhoneHub on the phone and scan the QR (it pairs over USB automatically)."
