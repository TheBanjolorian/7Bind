"""The game files 7Bind backs up, grouped the way the window offers them.

Paths are relative to a channel folder (...\\StarCitizen\\LIVE) and always written
with forward slashes inside backups, so a backup is the same on every PC.
"""

from __future__ import annotations

import re
from pathlib import Path

PROFILE = "user/client/0/Profiles/default"
ACTIONMAPS = f"{PROFILE}/actionmaps.xml"
ATTRIBUTES = f"{PROFILE}/attributes.xml"
ATTRIBUTES_VR = f"{PROFILE}/attributesVR.xml"
MAPPINGS_DIR = "user/client/0/controls/mappings"
USER_CFG = "user.cfg"
DEFAULT_ACTIONS = "user/client/0/Profiles/defaultActions.xml"   # read for the build number only

# Groups the user can tick when copying or restoring.
GROUPS = {
    "bindings": "Key bindings and curves",
    "settings": "Game settings (graphics, FOV, audio, sensitivity)",
    "profiles": "Saved control profiles",
    "user_cfg": "user.cfg (merged, 7Hills Link lines kept)",
}
DEFAULT_GROUPS = ("bindings", "settings", "profiles")

MAX_FILE = 4 * 1024 * 1024   # a profile file is a few KB; anything this big is not ours


def group_of(rel: str) -> str | None:
    if rel == ACTIONMAPS:
        return "bindings"
    if rel in (ATTRIBUTES, ATTRIBUTES_VR):
        return "settings"
    if rel.startswith(MAPPINGS_DIR + "/") and rel.lower().endswith(".xml"):
        return "profiles"
    if rel == USER_CFG:
        return "user_cfg"
    return None


_SAFE = re.compile(r"^[A-Za-z0-9 _.()\-]+$")


def is_safe_rel(rel: str) -> bool:
    """Only paths 7Bind itself produces: no drive, no '..', known folders, plain file names."""
    if not rel or "\\" in rel or rel.startswith("/") or ":" in rel:
        return False
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return False
    if group_of(rel) is None:
        return False
    return bool(_SAFE.match(parts[-1]))


def read_channel(folder: Path) -> dict[str, bytes]:
    """All backed-up files that exist in this channel folder."""
    out: dict[str, bytes] = {}
    for rel in (ACTIONMAPS, ATTRIBUTES, ATTRIBUTES_VR, USER_CFG):
        p = folder / rel
        try:
            if p.is_file() and p.stat().st_size <= MAX_FILE:
                out[rel] = p.read_bytes()
        except OSError:
            continue
    mdir = folder / MAPPINGS_DIR
    try:
        for p in sorted(mdir.glob("*.xml")):
            rel = f"{MAPPINGS_DIR}/{p.name}"
            if is_safe_rel(rel) and p.is_file() and p.stat().st_size <= MAX_FILE:
                out[rel] = p.read_bytes()
    except OSError:
        pass
    return out


def pick(files: dict[str, bytes], groups: set[str] | tuple[str, ...]) -> dict[str, bytes]:
    g = set(groups)
    return {rel: data for rel, data in files.items() if group_of(rel) in g}
