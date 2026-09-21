"""A stable id for this computer, so a licence key works on one machine only.

It is derived from the operating system's own install id (``/etc/machine-id`` on Linux,
``MachineGuid`` on Windows, the hardware UUID on macOS), hashed so the raw id is never
shown or sent. Reinstalling the operating system gives a new id; the licence server lets
the owner move a licence to it.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import uuid


def _raw_id() -> str:
    if sys.platform.startswith("win"):
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                return str(winreg.QueryValueEx(key, "MachineGuid")[0])
        except OSError:
            pass
    elif sys.platform == "darwin":
        try:
            out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True, text=True, timeout=5).stdout
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    return line.split('"')[-2]
        except (OSError, subprocess.SubprocessError, IndexError):
            pass
    else:
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                with open(path, encoding="ascii") as handle:
                    value = handle.read().strip()
                if value:
                    return value
            except OSError:
                continue
    # Last resort: a network card's address.
    return f"node-{uuid.getnode():012x}"


def machine_id() -> str:
    """``GM-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX``: this computer, as licence keys name it."""
    digest = hashlib.sha256(f"granum-machine-v1:{_raw_id()}".encode()).hexdigest()[:24].upper()
    return "GM-" + "-".join(digest[i:i + 4] for i in range(0, 24, 4))
