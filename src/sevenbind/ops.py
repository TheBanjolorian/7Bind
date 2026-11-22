"""Copy between channels and Restore from a backup.

Both go plan -> (player checks) -> execute. Execute always:
1. refuses if Star Citizen from the target channel is running,
2. keeps the target's current files (a before_restore backup + a raw copy in safety\\),
3. moves joystick bindings to the right devices,
4. merges user.cfg so 7Hills Link's lines stay,
5. writes through writer.write_files (which guards LIVE).
Copy never targets LIVE. Restore needs the player to type RESTORE, for any channel.
"""

from __future__ import annotations

import shutil
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from . import actionmaps, backup, detect, gamefiles, remap, usercfg, writer
from .paths import sub
from .store import Store

SAFETY_DAYS = 30


class OpError(Exception):
    pass


@dataclass
class Plan:
    id: str
    mode: str                         # copy | restore
    source_label: str
    source_channel: str
    source_files: dict[str, bytes]
    target_channel: str
    target_folder: Path
    groups: list[str]
    backup_id: str | None = None
    matches: list[remap.Match] = field(default_factory=list)
    target_devices: list[actionmaps.Device] = field(default_factory=list)
    devices_known: bool = True
    overrides: dict[int, int | None] = field(default_factory=dict)
    created: float = field(default_factory=time.time)

    def mapping(self) -> dict[int, int | None]:
        if not self.devices_known:
            return {}
        return remap.mapping_from(self.matches, self.overrides)

    def as_dict(self) -> dict:
        src = _profile(self.source_files)
        per: dict[int, int] = {}
        if src:
            for b in src.active:
                if b.kind == "joystick" and b.instance is not None:
                    per[b.instance] = per.get(b.instance, 0) + 1
        tgt_files = gamefiles.read_channel(self.target_folder)
        tgt = _profile(tgt_files)
        mapping = self.mapping()
        skipped = sum(n for inst, n in per.items() if self.devices_known and mapping.get(inst, inst) is None)
        return {
            "id": self.id, "mode": self.mode, "source": self.source_label, "source_channel": self.source_channel,
            "backup_id": self.backup_id, "target": self.target_channel, "groups": self.groups,
            "group_names": gamefiles.GROUPS,
            "target_is_live": self.target_channel == "LIVE",
            "devices_known": self.devices_known,
            "devices": [m.as_dict(per.get(m.source.instance, 0)) | {"to": mapping.get(m.source.instance, m.source.instance) if self.devices_known else m.source.instance,
                                                                       "status": _status(m, mapping, self.devices_known)}
                        for m in self.matches],
            "target_devices": [{"instance": d.instance, "name": d.name} for d in self.target_devices
                               if d.kind == "joystick" and d.product],
            "skipped_bindings": skipped,
            "source_summary": backup.summarize(self.source_files),
            "target_custom_bindings": len(tgt.active) if tgt else 0,
            "target_has_files": bool(tgt_files),
            "game_running": game_running(self.target_folder),
        }


def _status(m: remap.Match, mapping: dict, known: bool) -> str:
    if not known:
        return "kept"
    to = mapping.get(m.source.instance, m.source.instance)
    if to is None:
        return "missing"
    return "same" if to == m.source.instance else "moved"


def _profile(files: dict[str, bytes]) -> actionmaps.Profile | None:
    data = files.get(gamefiles.ACTIONMAPS)
    if not data:
        return None
    try:
        return actionmaps.parse(data)
    except ET.ParseError:
        return None


def game_running(folder: Path) -> bool:
    target = str(Path(folder)).lower()
    return any(str(f).lower() == target for f in detect.running_game_folders())


def _devices_on_pc(target_folder: Path, other_folders: list[Path]) -> tuple[list[actionmaps.Device], bool]:
    """Device list as the game wrote it for the target; else from another channel on this PC."""
    for folder in [target_folder] + [f for f in other_folders if f != target_folder]:
        p = _profile(gamefiles.read_channel(folder))
        if p and p.joysticks:
            return p.devices, True
    return [], False


def make_plan(mode: str, source_label: str, source_channel: str, source_files: dict[str, bytes],
              target: detect.Install, all_installs: list[detect.Install], groups: list[str],
              backup_id: str | None = None) -> Plan:
    if mode == "copy" and target.channel == "LIVE":
        raise OpError("LIVE is the template. Copy never writes to it.")
    if mode == "copy" and target.channel == source_channel:
        raise OpError("Pick two different channels.")
    groups = [g for g in groups if g in gamefiles.GROUPS] or list(gamefiles.DEFAULT_GROUPS)
    src = _profile(source_files)
    devices, known = _devices_on_pc(target.folder, [i.folder for i in all_installs])
    matches = remap.match_devices(src, devices) if src else []
    return Plan(str(uuid.uuid4()), mode, source_label, source_channel, source_files, target.channel,
                target.folder, groups, backup_id, matches, devices, known)


def _safety_copy(folder: Path, channel: str) -> Path | None:
    files = gamefiles.read_channel(folder)
    if not files:
        return None
    dest = sub("safety") / channel / time.strftime("%Y%m%d-%H%M%S")
    for rel, data in files.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return dest


def prune_safety() -> None:
    root = sub("safety")
    cutoff = time.time() - SAFETY_DAYS * 86400
    for ch in root.iterdir() if root.exists() else []:
        for d in ch.iterdir() if ch.is_dir() else []:
            try:
                if d.is_dir() and d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                continue


def build_files(plan: Plan) -> tuple[dict[str, bytes], dict]:
    chosen = gamefiles.pick(plan.source_files, plan.groups)
    stats = {"skipped": 0, "moved": 0}
    am = chosen.get(gamefiles.ACTIONMAPS)
    if am and plan.devices_known:
        chosen[gamefiles.ACTIONMAPS], stats = remap.apply(am, plan.mapping(), plan.target_devices)
    if gamefiles.USER_CFG in chosen:
        try:
            current = (plan.target_folder / gamefiles.USER_CFG).read_text(encoding="utf-8", errors="replace")
        except OSError:
            current = ""
        src = chosen[gamefiles.USER_CFG].decode("utf-8", errors="replace")
        chosen[gamefiles.USER_CFG] = usercfg.merge(src, current).encode("utf-8")
    return chosen, stats


def execute(plan: Plan, store: Store, confirmation: writer.Confirmation | None = None) -> dict:
    if plan.mode == "copy" and plan.target_channel == "LIVE":
        raise OpError("LIVE is the template. Copy never writes to it.")
    if plan.mode == "restore" and not isinstance(confirmation, writer.Confirmation):
        raise OpError(f"Type {writer.CONFIRM_WORD} to confirm the restore.")
    if game_running(plan.target_folder):
        raise OpError(f"Close Star Citizen ({plan.target_channel}) first. The game rewrites these files when it exits.")
    files, stats = build_files(plan)
    if not files:
        raise OpError("Nothing to write: the source has none of the chosen files.")
    before = backup.backup_channel(store, plan.target_channel, plan.target_folder, kind="before_restore", force=True)
    safety = _safety_copy(plan.target_folder, plan.target_channel)
    written = writer.write_files(plan.target_folder, files, confirmation=confirmation)
    prune_safety()
    return {"written": written, "stats": stats,
            "before_restore": (before.get("backup") or {}).get("id"),
            "safety_folder": str(safety) if safety else None}
