"""Local backup store: %LOCALAPPDATA%\\7Bind\\backups. Nothing here is ever deleted by 7Bind.

Each backup is one gzip'd JSON file {meta, files}; files are base64 so a backup is
a single portable blob (the same blob is uploaded to 7hills.space). index.json
holds the meta of every backup for fast listing and is rebuilt from the blobs if lost.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .paths import sub

KINDS = ("auto", "version_snapshot", "named", "before_restore", "manual")
PINNED = ("version_snapshot", "named", "before_restore")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def content_hash(files: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(rel.encode())
        h.update(b"\0")
        h.update(hashlib.sha256(files[rel]).digest())
    return h.hexdigest()


def encode(meta: dict, files: dict[str, bytes]) -> bytes:
    body = {"format": 1, "meta": meta, "files": {k: base64.b64encode(v).decode() for k, v in files.items()}}
    return gzip.compress(json.dumps(body, separators=(",", ":")).encode(), mtime=0)


def decode(blob: bytes) -> tuple[dict, dict[str, bytes]]:
    body = json.loads(gzip.decompress(blob))
    files = {k: base64.b64decode(v) for k, v in (body.get("files") or {}).items()}
    return body.get("meta") or {}, files


class Store:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or sub("backups")
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"
        self.lock = threading.RLock()
        self.items: list[dict] = self._load_index()

    # ---------------------------------------------------------------- index

    def _load_index(self) -> list[dict]:
        try:
            items = json.loads(self.index_path.read_text(encoding="utf-8"))
            if isinstance(items, list):
                known = {i.get("id") for i in items}
                blobs = {p.name[:-8] for p in self.root.glob("*.json.gz")}
                if blobs <= known:
                    return items
        except (OSError, ValueError):
            pass
        return self._rebuild()

    def _rebuild(self) -> list[dict]:
        items = []
        for p in sorted(self.root.glob("*.json.gz")):
            try:
                meta, _ = decode(p.read_bytes())
                if meta.get("id"):
                    items.append(meta)
            except Exception:
                continue
        items.sort(key=lambda m: m.get("created_at") or "")
        self.items = items
        self._save_index()
        return items

    def _save_index(self) -> None:
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, indent=0), encoding="utf-8")
        tmp.replace(self.index_path)

    # ---------------------------------------------------------------- read

    def list(self, channel: str | None = None) -> list[dict]:
        with self.lock:
            out = [m for m in self.items if channel is None or m.get("channel") == channel]
        return sorted(out, key=lambda m: m.get("created_at") or "", reverse=True)

    def latest(self, channel: str) -> dict | None:
        items = self.list(channel)
        return items[0] if items else None

    def get(self, backup_id: str) -> dict | None:
        with self.lock:
            return next((m for m in self.items if m.get("id") == backup_id), None)

    def blob(self, backup_id: str) -> bytes:
        return (self.root / f"{backup_id}.json.gz").read_bytes()

    def files(self, backup_id: str) -> dict[str, bytes]:
        return decode(self.blob(backup_id))[1]

    # ---------------------------------------------------------------- write

    def add(self, meta: dict, files: dict[str, bytes]) -> dict:
        meta = dict(meta)
        meta.setdefault("id", str(uuid.uuid4()))
        meta.setdefault("created_at", now_iso())
        meta.setdefault("last_seen_at", meta["created_at"])
        meta["content_hash"] = content_hash(files)
        meta["pinned"] = meta.get("kind") in PINNED or bool(meta.get("name"))
        meta.setdefault("cloud", None)
        blob = encode(meta, files)
        meta["size"] = len(blob)
        path = self.root / f"{meta['id']}.json.gz"
        tmp = path.with_suffix(".part")
        tmp.write_bytes(blob)
        tmp.replace(path)
        with self.lock:
            self.items.append(meta)
            self._save_index()
        return meta

    def add_blob(self, blob: bytes) -> dict:
        """A backup downloaded from 7hills.space; kept locally as-is."""
        meta, files = decode(blob)
        if not meta.get("id"):
            raise ValueError("Backup has no id")
        existing = self.get(meta["id"])
        if existing:
            return existing
        return self.add(meta, files)

    def update(self, backup_id: str, **fields) -> dict | None:
        """Change index-only fields (name, last_seen_at, cloud). The blob keeps its original meta."""
        with self.lock:
            m = self.get(backup_id)
            if not m:
                return None
            m.update(fields)
            if fields.get("name"):
                m["pinned"] = True
            self._save_index()
            return m

    def seen(self, backup_id: str) -> None:
        self.update(backup_id, last_seen_at=now_iso())

    def pending_upload(self) -> list[dict]:
        with self.lock:
            return [m for m in sorted(self.items, key=lambda m: m.get("created_at") or "") if not m.get("cloud")]


def wait_for_files_settled(paths: list[Path], quiet: float = 3.0, timeout: float = 30.0) -> None:
    """The game writes several files on exit; wait until their mtimes stop moving."""
    end = time.time() + timeout
    last = None
    stable_since = time.time()
    while time.time() < end:
        cur = []
        for p in paths:
            try:
                cur.append(p.stat().st_mtime)
            except OSError:
                cur.append(None)
        if cur != last:
            last, stable_since = cur, time.time()
        elif time.time() - stable_since >= quiet:
            return
        time.sleep(0.5)
