"""One 7Bind at a time.

The first 7Bind holds a named lock and listens on 127.0.0.1 for a "show" message.
A second start (double-click, autostart, a shortcut) finds the lock, asks the
running one to show its window, and exits. On Windows the lock is a named
mutex; elsewhere an exclusive lock file.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from typing import Callable

from .paths import data_dir

MUTEX_NAME = "Local\\7Bind.single-instance"
_ERROR_ALREADY_EXISTS = 183
_handle = None      # keeps the mutex / lock file alive for the process lifetime


def _port_file():
    return data_dir() / "instance.json"


def acquire(wait: float = 0.0) -> bool:
    """True if this process is now the only 7Bind. wait: seconds to keep trying (after an update)."""
    global _handle
    end = time.time() + wait
    while True:
        if _try_lock():
            return True
        if time.time() >= end:
            return False
        time.sleep(0.5)


def _try_lock() -> bool:
    global _handle
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k32.CreateMutexW(None, False, MUTEX_NAME)
        err = ctypes.get_last_error()
        if not h:
            return True        # cannot tell; do not block the start
        if err == _ERROR_ALREADY_EXISTS:
            k32.CloseHandle(h)
            return False
        _handle = h
        return True
    import fcntl
    f = open(data_dir() / "instance.lock", "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _handle = f
    return True


def listen(on_show: Callable[[], None], on_quit: Callable[[], None] | None = None) -> None:
    """Serve "show" (and "quit") from later starts. Runs in a daemon thread."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    port = srv.getsockname()[1]
    try:
        _port_file().write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    except OSError:
        pass

    def loop():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(2)
                try:
                    msg = conn.recv(32).decode("ascii", "ignore").strip()
                except OSError:
                    continue
                if msg == "show":
                    on_show()
                elif msg == "quit" and on_quit:
                    on_quit()
    threading.Thread(target=loop, name="single-instance", daemon=True).start()


def tell_running(message: str = "show") -> bool:
    """Send a message to the running 7Bind. True if it answered."""
    try:
        port = int(json.loads(_port_file().read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as s:
            s.sendall(message.encode("ascii"))
        return True
    except OSError:
        return False
