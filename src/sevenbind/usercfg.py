"""Merges user.cfg so 7Hills Link's telemetry lines always survive a copy or restore.

7Bind never adds telemetry lines itself. When user.cfg is copied, the target
keeps its own Link lines; everything else comes from the source.
"""

from __future__ import annotations

LINK_KEYS = ("grpc.client.server.enabled", "grpc.client.server.port")
LINK_PREFIX = "server.game.telemetry."
LINK_COMMENT = "-- 7hills link"


def _key(line: str) -> str | None:
    s = line.strip()
    if not s or s.startswith("--") or s.startswith(";") or "=" not in s:
        return None
    return s.split("=", 1)[0].strip().lower()


def is_link_line(line: str) -> bool:
    s = line.strip().lower()
    if s.startswith(LINK_COMMENT):
        return True
    k = _key(line)
    return bool(k and (k in LINK_KEYS or k.startswith(LINK_PREFIX)))


def merge(source: str, target: str) -> str:
    src = [l for l in source.splitlines() if not is_link_line(l)]
    link = [l for l in target.splitlines() if is_link_line(l)]
    # Source keys win; drop duplicate keys (last one stays, as the game reads it).
    seen: set[str] = set()
    out_rev: list[str] = []
    for line in reversed(src):
        k = _key(line)
        if k and k in seen:
            continue
        if k:
            seen.add(k)
        out_rev.append(line)
    body = list(reversed(out_rev))
    while body and not body[-1].strip():
        body.pop()
    while body and not body[0].strip():
        body.pop(0)
    if link:
        if body:
            body.append("")
        body.extend(link)
    return "\n".join(body) + "\n" if body else ""
