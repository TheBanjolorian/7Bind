"""The only code in 7Bind that writes into a Star Citizen folder.

Rules (from Costas, 2026-11-22):
- LIVE is the template. Nothing writes to LIVE except Restore, and only after
  the player typed RESTORE. Copy, automatic backups, anything else: refused.
- Every path must stay inside the channel folder and be a file 7Bind manages.
- Writes are atomic: a .7bind.tmp file next to the target, then a rename.
"""

from __future__ import annotations

import os
from pathlib import Path

from .gamefiles import is_safe_rel

CONFIRM_WORD = "RESTORE"


class Refused(Exception):
    pass


class Confirmation:
    """Proof the player typed RESTORE for one restore. Single use."""

    __slots__ = ("_used", "_target")

    def __init__(self, _key: object, target: str) -> None:
        if _key is not _KEY:
            raise Refused("A confirmation can only come from confirm()")
        self._used = False
        self._target = target.upper()

    def spend(self, channel: str) -> None:
        if self._used:
            raise Refused("This confirmation was already used")
        if channel.upper() != self._target:
            raise Refused("The confirmation was given for another channel")
        self._used = True


_KEY = object()


def confirm(typed: str, target_channel: str) -> Confirmation:
    if (typed or "") != CONFIRM_WORD:
        raise Refused(f"Type {CONFIRM_WORD} to confirm")
    return Confirmation(_KEY, target_channel)


def is_live(folder: Path) -> bool:
    return folder.name.upper() == "LIVE"


def write_files(folder: Path, files: dict[str, bytes], *, confirmation: Confirmation | None = None) -> list[str]:
    """Write files (relative paths) into a channel folder. Returns the paths written."""
    folder = Path(folder)
    channel = folder.name.upper()
    if is_live(folder):
        if not isinstance(confirmation, Confirmation):
            raise Refused("LIVE is the template. Only Restore with RESTORE typed can change it.")
        confirmation.spend(channel)
    elif confirmation is not None:
        confirmation.spend(channel)
    base = folder.resolve()
    targets: list[tuple[Path, bytes, str]] = []
    for rel, data in files.items():
        if not is_safe_rel(rel):
            raise Refused(f"Not a file 7Bind manages: {rel}")
        p = (folder / rel).resolve()
        if base not in p.parents:
            raise Refused(f"Outside the game folder: {rel}")
        targets.append((p, data, rel))
    written = []
    for p, data, rel in targets:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".7bind.tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
        if p.read_bytes() != data:
            raise OSError(f"Verify failed for {rel}")
        written.append(rel)
    return written
