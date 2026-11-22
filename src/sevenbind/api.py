"""Talks to 7Net (www.7hills.space).

Linking reuses 7Net's existing PC link (the same one 7Hills Link uses): if 7Hills
Link is already linked on this PC, 7Bind uses that key and you are signed in at once.

Backup endpoints (see docs/API.md) only ever receive uploads and serve downloads
the player asked for in 7Bind. 7Net cannot tell 7Bind to write anything.
"""

from __future__ import annotations

import json
import os
import platform
import urllib.error
import urllib.request

from . import __version__
from .paths import data_dir

BASE = os.environ.get("SEVENBIND_BASE", "https://www.7hills.space")
UA = f"7Bind/{__version__} ({platform.system()} {platform.release()})"
KEYRING_SERVICE = "7Bind"
LINK_KEYRING_SERVICE = "7HillsLink"   # 7Hills Link's key; read only


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


def _request(method: str, path: str, data: bytes | None = None, token: str | None = None,
             content_type: str = "application/json", timeout: float = 20, raw: bool = False):
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("User-Agent", UA)
    if data is not None:
        req.add_header("Content-Type", content_type)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read() or b""
            if raw:
                return body
            return json.loads(body or b"{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read() or b"{}").get("error", e.reason)
        except Exception:
            msg = str(e.reason)
        raise ApiError(e.code, str(msg)) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ApiError(0, str(e)) from None


def _json(method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    return _request(method, path, data, token)


def device_name() -> str:
    return (platform.node() or "PC")[:50] + " · 7Bind"


# ------------------------------------------------------------------ linking (existing 7Net PC link)

def start_link() -> dict:
    return _json("POST", "/api/telemetry/link/start", {"device_name": device_name()})


def poll_link(code: str, poll_secret: str) -> dict:
    return _json("POST", "/api/telemetry/link/poll", {"code": code, "poll_secret": poll_secret})


def whoami(token: str) -> dict:
    """{member: {handle, ...}, settings: {...}} for the linked PC."""
    return _json("GET", "/api/telemetry/device/settings", token=token)


# ------------------------------------------------------------------ backups (docs/API.md)

def upload_backup(token: str, meta: dict, blob: bytes) -> dict:
    """POST the backup blob; meta travels in headers so the body stays the exact blob."""
    req_meta = {k: meta.get(k) for k in ("id", "channel", "kind", "name", "game_version", "game_build",
                                          "content_hash", "created_at", "pc")}
    path = "/api/bind/backups?meta=" + urllib.request.quote(json.dumps(req_meta, separators=(",", ":")))
    return _request("POST", path, blob, token, content_type="application/gzip", timeout=60)


def seen_backup(token: str, cloud_id: str) -> dict:
    return _json("PATCH", f"/api/bind/backups/{cloud_id}/seen", {}, token)


def list_backups(token: str, channel: str | None = None) -> list[dict]:
    q = f"?channel={channel}" if channel else ""
    r = _json("GET", "/api/bind/backups" + q, token=token)
    return r.get("backups") or []


def download_backup(token: str, cloud_id: str) -> bytes:
    return _request("GET", f"/api/bind/backups/{cloud_id}/download", token=token, raw=True, timeout=60)


# ------------------------------------------------------------------ key

def _key_file():
    return data_dir() / "device.key"


def _keyring_get(service: str) -> str | None:
    try:
        import keyring  # type: ignore
        return keyring.get_password(service, "device") or None
    except Exception:
        return None


def load_token() -> tuple[str | None, str]:
    """(token, source): own key first, then 7Hills Link's key on this PC."""
    t = _keyring_get(KEYRING_SERVICE)
    if t:
        return t, "7bind"
    f = _key_file()
    if f.exists():
        t = f.read_text().strip()
        if t:
            return t, "7bind"
    if not signed_out():
        t = _keyring_get(LINK_KEYRING_SERVICE)
        if t:
            return t, "7hills-link"
    return None, ""


def signed_out() -> bool:
    """The player signed 7Bind out: do not borrow 7Hills Link's key until they link again."""
    return (data_dir() / "signed_out").exists()


def set_signed_out(on: bool) -> None:
    f = data_dir() / "signed_out"
    if on:
        f.write_text("1")
    elif f.exists():
        f.unlink()


def save_token(token: str) -> None:
    try:
        import keyring  # type: ignore
        keyring.set_password(KEYRING_SERVICE, "device", token)
        return
    except Exception:
        pass
    _key_file().write_text(token)


def clear_token() -> None:
    """Forget 7Bind's own key. 7Hills Link's key is never touched."""
    try:
        import keyring  # type: ignore
        keyring.delete_password(KEYRING_SERVICE, "device")
    except Exception:
        pass
    f = _key_file()
    if f.exists():
        f.unlink()
