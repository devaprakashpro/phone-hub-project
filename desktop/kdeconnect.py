"""
KDE Connect bridge for PhoneHub.

KDE Connect is already installed system-wide (the daemon kdeconnectd runs and
exposes kdeconnect-cli + a D-Bus API). Rather than rebuild its large Qt/KF
codebase, PhoneHub drives the running daemon: list/pair devices, ring, share
files, push clipboard/text, ping, battery. The phone side is the KDE Connect
Android app (paired once in the app).

All calls are best-effort and never raise — the UI shows the returned message.
"""
import shutil
import subprocess


class KdeConnect:
    CLI = "kdeconnect-cli"

    @staticmethod
    def available():
        return shutil.which(KdeConnect.CLI) is not None

    @staticmethod
    def _run(args, timeout=15):
        try:
            r = subprocess.run([KdeConnect.CLI] + args,
                               capture_output=True, text=True, timeout=timeout)
            out = (r.stdout or "").strip()
            err = (r.stderr or "").strip()
            return r.returncode == 0, (out or err)
        except Exception as e:
            return False, str(e)

    @staticmethod
    def devices(available_only=True):
        """Return [(id, name), ...]."""
        flag = "-a" if available_only else "-l"
        ok, out = KdeConnect._run([flag, "--id-name-only"])
        devs = []
        if ok:
            for ln in out.splitlines():
                ln = ln.strip()
                # skip the trailing summary line, e.g. "0 devices found"
                if not ln or ln.endswith("devices found") or ln.endswith("device found"):
                    continue
                parts = ln.split(" ", 1)
                if len(parts) == 2:
                    devs.append((parts[0], parts[1]))
                else:
                    devs.append((parts[0], parts[0]))
        return devs

    @staticmethod
    def refresh():
        return KdeConnect._run(["--refresh"], timeout=8)

    @staticmethod
    def pair(dev):
        return KdeConnect._run(["-d", dev, "--pair"], timeout=30)

    @staticmethod
    def unpair(dev):
        return KdeConnect._run(["-d", dev, "--unpair"])

    @staticmethod
    def ring(dev):
        return KdeConnect._run(["-d", dev, "--ring"])

    @staticmethod
    def ping(dev):
        return KdeConnect._run(["-d", dev, "--ping"])

    @staticmethod
    def send_clipboard(dev):
        return KdeConnect._run(["-d", dev, "--send-clipboard"])

    @staticmethod
    def share_text(dev, text):
        return KdeConnect._run(["-d", dev, "--share-text", text])

    @staticmethod
    def share_file(dev, path):
        return KdeConnect._run(["-d", dev, "--share", path], timeout=30)

    @staticmethod
    def battery(dev):
        """Battery % via the daemon D-Bus, or None."""
        path = f"/modules/kdeconnect/devices/{dev}/battery"
        try:
            r = subprocess.run(
                ["gdbus", "call", "--session", "--dest", "org.kde.kdeconnect",
                 "--object-path", path, "--method", "org.freedesktop.DBus.Properties.Get",
                 "org.kde.kdeconnect.device.battery", "charge"],
                capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                # output like: (<23>,)
                digits = "".join(c for c in r.stdout if c.isdigit())
                return int(digits) if digits else None
        except Exception:
            pass
        return None
