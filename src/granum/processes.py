"""Starting and watching child processes the same way on Linux and Windows.

The service runs without a console on Windows, so every console program it starts (pip,
a trainer, an environment check) must be told not to open a console window of its own.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

IS_WINDOWS = os.name == "nt"
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def no_window() -> dict[str, Any]:
    """Popen options that keep a console program from flashing a window on Windows."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WINDOWS else {}


def detached_options() -> dict[str, Any]:
    """Popen options for a process that outlives its parent and belongs to no console.

    POSIX: its own session. Windows: its own process group, no console window, and out of
    the parent's job, so closing the window that started it does not stop it.
    """
    if not IS_WINDOWS:
        return {"start_new_session": True}
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    return {"creationflags": flags | _CREATE_BREAKAWAY_FROM_JOB}


def popen_detached(command: list[str], **options: Any) -> subprocess.Popen:
    try:
        return subprocess.Popen(command, **options, **detached_options())
    except PermissionError:
        if not IS_WINDOWS:
            raise
        # A job that forbids breaking away: stay in it rather than not start at all.
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        return subprocess.Popen(command, **options, creationflags=flags)


def windows_process_alive(pid: int) -> bool:
    """Whether a process is running, without touching it (``os.kill(pid, 0)`` kills on Windows)."""
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def console_python(executable: str) -> str:
    """The console Python beside ``executable``: a windowed Python has no usable output streams,
    so children that print (pip, trainers, the service) run with ``python.exe`` and no window."""
    if IS_WINDOWS:
        # pythonw.exe, or the app's Granum.exe (a renamed pythonw.exe with Granum's icon).
        head, tail = os.path.split(executable)
        if tail.lower() != "python.exe" and os.path.exists(os.path.join(head, "python.exe")):
            return os.path.join(head, "python.exe")
    return executable
