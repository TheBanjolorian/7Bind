"""Makes backups of a channel: read files, skip when nothing changed, summarise.

kinds: auto (game closed / app start), version_snapshot (first backup on a new
game build, always kept even if files are identical), named / manual (Back up now),
before_restore (taken right before 7Bind writes into a channel).
"""

from __future__ import annotations

import platform
import xml.etree.ElementTree as ET
from pathlib import Path

from . import actionmaps, gamefiles, version
from .store import Store, content_hash

SETTING_LABELS = {
    "FOV": "Field of view", "AudioMasterVolume": "Master volume", "AudioMusicVolume": "Music volume",
    "Width": "Resolution width", "Height": "Resolution height", "WindowMode": "Window mode",
    "MouseSensitivity": "Mouse sensitivity", "SysSpec": "Graphics quality", "VSync": "VSync",
    "HeadtrackingSource": "Head tracking source", "HeadtrackingToggle": "Head tracking",
    "UpscalingTechnique": "Upscaling", "Weapon_Setting_FallbackConvergenceDistance": "Convergence distance",
}


def attributes(data: bytes | None) -> dict[str, str]:
    if not data:
        return {}
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return {}
    return {a.get("name"): a.get("value") for a in root.iter("Attr") if a.get("name")}


def settings_diff(old: bytes | None, new: bytes | None) -> list[dict]:
    a, b = attributes(old), attributes(new)
    out = []
    for k in sorted(set(a) | set(b)):
        if k.startswith("selectedShipURN"):
            continue
        if a.get(k) != b.get(k):
            out.append({"name": k, "label": SETTING_LABELS.get(k, k), "before": a.get(k), "after": b.get(k)})
    return out


def summarize(files: dict[str, bytes]) -> dict:
    am = files.get(gamefiles.ACTIONMAPS)
    s: dict = {"bindings": 0, "removed": 0, "curves": 0, "devices": [], "conflicts": [],
               "files": sorted(files), "has_bindings": am is not None}
    if am:
        try:
            s.update(actionmaps.summary(actionmaps.parse(am)))
        except ET.ParseError:
            s["parse_error"] = True
    return s


def changes(prev_files: dict[str, bytes] | None, files: dict[str, bytes]) -> dict:
    if prev_files is None:
        return {"first": True}
    out: dict = {}
    try:
        old = actionmaps.parse(prev_files[gamefiles.ACTIONMAPS]) if gamefiles.ACTIONMAPS in prev_files else None
        new = actionmaps.parse(files[gamefiles.ACTIONMAPS]) if gamefiles.ACTIONMAPS in files else None
        if new is not None:
            out.update(actionmaps.diff(old, new))
    except ET.ParseError:
        pass
    sd = settings_diff(prev_files.get(gamefiles.ATTRIBUTES), files.get(gamefiles.ATTRIBUTES))
    out["settings_changed"] = [d["label"] for d in sd]
    other = [r for r in set(prev_files) ^ set(files)] + [
        r for r in set(prev_files) & set(files)
        if prev_files[r] != files[r] and r not in (gamefiles.ACTIONMAPS, gamefiles.ATTRIBUTES)]
    out["files_changed"] = sorted(other)
    return out


def describe(meta: dict) -> str:
    """Short 'What changed' text for lists."""
    if meta.get("kind") == "version_snapshot":
        return "Version snapshot"
    if meta.get("kind") == "before_restore":
        return "Before restore"
    c = meta.get("changes") or {}
    if c.get("first"):
        return "First backup"
    parts = []
    n = c.get("bindings_changed") or 0
    if n:
        parts.append(f"{n} binding{'s' if n != 1 else ''}")
    parts += (c.get("settings_changed") or [])[:2]
    if c.get("files_changed"):
        parts.append("profiles" if any("mappings" in f for f in c["files_changed"]) else "user.cfg")
    return " · ".join(parts) or "No changes"


def backup_channel(store: Store, channel: str, folder: Path, *, kind: str = "auto", name: str | None = None,
                   force: bool = False) -> dict:
    """Returns {"result": "saved"|"unchanged"|"empty", "backup": meta or None}."""
    files = gamefiles.read_channel(folder)
    if not files:
        return {"result": "empty", "backup": None}
    ver = version.game_build(folder)
    latest = store.latest(channel)
    h = content_hash(files)
    new_build = latest is not None and ver.get("build") and latest.get("game_build") != ver.get("build")
    if latest and latest.get("content_hash") == h and not new_build and not force and not name:
        # Identical files are never stored twice.
        store.seen(latest["id"])
        return {"result": "unchanged", "backup": latest}
    if new_build and kind == "auto":
        kind = "version_snapshot"
    if name and kind in ("auto", "manual"):
        kind = "named"
    prev_files = None
    if latest:
        try:
            prev_files = store.files(latest["id"])
        except Exception:
            prev_files = None
    meta = {
        "channel": channel, "kind": kind, "name": (name or "").strip()[:60] or None,
        "game_version": ver.get("version"), "game_build": ver.get("build"),
        "pc": (platform.node() or "PC")[:60],
        "summary": summarize(files),
        "changes": changes(prev_files, files),
    }
    saved = store.add(meta, files)
    return {"result": "saved", "backup": saved}
