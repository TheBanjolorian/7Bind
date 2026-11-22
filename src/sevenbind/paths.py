"""Where 7Bind keeps its files, and where bundled files live when frozen."""

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    """%LOCALAPPDATA%\\7Bind on Windows, ~/.7bind elsewhere. SEVENBIND_HOME overrides (tests)."""
    override = os.environ.get("SEVENBIND_HOME")
    if override:
        p = Path(override)
    else:
        base = os.environ.get("LOCALAPPDATA")
        p = Path(base) / "7Bind" if base else Path.home() / ".7bind"
    p.mkdir(parents=True, exist_ok=True)
    return p


def sub(name: str) -> Path:
    p = data_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def resource(*parts: str) -> Path:
    """A file shipped with the app (PyInstaller unpacks to sys._MEIPASS)."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    frozen = root / "sevenbind" / Path(*parts)
    return frozen if frozen.exists() else Path(__file__).resolve().parent / Path(*parts)
