"""Which game build a channel folder holds.

1. build_manifest.id in the channel folder (JSON the launcher writes), if it has a version.
2. BuildID in user\\client\\0\\Profiles\\defaultActions.xml (the game rewrites it on start).
Shown as major.minor (4.10) with the full build (4.10.201.48085) under it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .gamefiles import DEFAULT_ACTIONS

_BUILD_RE = re.compile(rb'BuildID="([0-9][0-9.]*)"')
_VER_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def short(build: str | None) -> str | None:
    m = _VER_RE.search(build or "")
    return f"{m.group(1)}.{m.group(2)}" if m else None


def _from_manifest(folder: Path) -> str | None:
    p = folder / "build_manifest.id"
    try:
        data = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, ValueError):
        return None
    d = data.get("Data", data) if isinstance(data, dict) else {}
    for key in ("Version", "version", "GameVersion"):
        v = d.get(key) if isinstance(d, dict) else None
        if isinstance(v, str) and _VER_RE.search(v):
            return _VER_RE.search(v).group(0)
    return None


def _from_default_actions(folder: Path) -> str | None:
    p = folder / DEFAULT_ACTIONS
    try:
        head = p.read_bytes()[:400]
    except OSError:
        return None
    m = _BUILD_RE.search(head)
    return m.group(1).decode() if m else None


def game_build(folder: Path) -> dict:
    build = _from_default_actions(folder) or _from_manifest(folder)
    return {"build": build, "version": short(build)}
