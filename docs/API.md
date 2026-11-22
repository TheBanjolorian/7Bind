# 7Bind ↔ 7hills.space API

What 7Net must offer for 7Bind 0.1. All endpoints use the existing telemetry PC link: `Authorization: Bearer <device key>` from `/api/telemetry/link/start` + `/poll` (the same key 7Hills Link uses). Responses are JSON unless noted; errors are `{ "error": "text" }` with a 4xx/5xx status.

**Hard rule:** there is no endpoint, push or flag through which 7Net asks 7Bind to back up, copy or restore. 7Bind only uploads on its own triggers and downloads a backup the player picked in 7Bind.

Until these exist, 7Bind treats `404/405/501` on `POST /api/bind/backups` as "the site does not take backups yet", keeps them locally and retries every minute.

## Backup blob

One gzip'd JSON file, the same bytes 7Bind stores locally:

```json
{
  "format": 1,
  "meta": {
    "id": "uuid (made by 7Bind, unique)",
    "channel": "LIVE | PTU | EPTU | TECH-PREVIEW | HOTFIX",
    "kind": "auto | version_snapshot | named | manual | before_restore",
    "name": "Before 5.0 | null",
    "game_version": "4.10",
    "game_build": "4.10.201.48085",
    "pc": "COSTASPC",
    "created_at": "2026-11-21T22:13:32Z",
    "content_hash": "sha256 over the files",
    "pinned": true,
    "summary": { "bindings": 60, "removed": 22, "curves": 2,
                 "devices": [{ "kind": "joystick", "instance": 1, "name": "VPC Panel #1", "guid": "02593344-...", "key": "js1", "bindings": 14, "curves": [], "inverted": [] }],
                 "conflicts": [{ "input": "js1_button11", "press": "tap", "actions": ["v_autoland", "v_toggle_all_doorlocks"], "labels": ["Autoland", "Lock/unlock all doors"], "device": "js1" }] },
    "changes": { "bindings_changed": 2, "settings_changed": ["Field of view"], "files_changed": [] }
  },
  "files": { "user/client/0/Profiles/default/actionmaps.xml": "<base64>", "user.cfg": "<base64>" }
}
```

File keys are relative to the channel folder with forward slashes; only these paths occur: `user/client/0/Profiles/default/actionmaps.xml`, `.../attributes.xml`, `.../attributesVR.xml`, `user/client/0/controls/mappings/<name>.xml`, `user.cfg`.

## Endpoints

### `POST /api/bind/backups?meta=<urlencoded JSON>`
Body: the blob (`Content-Type: application/gzip`). `meta` repeats `id, channel, kind, name, game_version, game_build, content_hash, created_at, pc` so the server can index without unpacking (it should still unpack and verify `content_hash`, and take `summary`/`changes` from the blob).
- Idempotent on `meta.id` (same id again → 200 with the existing row).
- Store the blob in a private bucket, e.g. `game-settings/<user_id>/<channel>/<id>.json.gz`.
- Limit: 1 MB per blob (real ones are ~5 KB).
- → `201 { "id": "<id>" }`

### `GET /api/bind/backups[?channel=LIVE]`
→ `{ "backups": [ { id, channel, kind, name, game_version, game_build, pc, created_at, content_hash, pinned, what, summary } ] }`, newest first, all of them (no retention). `what` is the short "What changed" text (optional).

### `GET /api/bind/backups/<id>/download`
→ the blob bytes (`application/gzip`). Only the owner's backups.

### `PATCH /api/bind/backups/<id>/seen`
Optional; 7Bind may call it when the game closed with no changes. → `{}`.

## Suggested table

`game_settings_backups`: `id uuid pk` (from 7Bind), `user_id`, `device_id` (PC link row), `channel`, `kind`, `name`, `pinned bool`, `game_version`, `game_build`, `pc`, `content_hash`, `size_bytes`, `summary jsonb`, `changes jsonb`, `storage_path`, `created_at`, `uploaded_at`, `last_seen_at`. RLS owner-only; index `(user_id, channel, created_at desc)`. Never deleted automatically.

The web pages (backup list, compare, bindings sheet, share links) are specified in the 7Net project doc `claude/link-settings-backup-spec-2026-11.md`. The same parser logic as `src/sevenbind/actionmaps.py` (labels, press types, conflicts) should be used there so the site and the app agree.
