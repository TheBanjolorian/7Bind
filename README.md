# 7Bind

Backs up your Star Citizen key bindings and game settings, copies them between game channels (LIVE → PTU) and puts them back after a reinstall. Made for [7Hills Industries](https://www.7hills.space); works for anyone.

**Download:** [7Bind.exe](https://github.com/TheBanjolorian/7Bind/releases/latest/download/7Bind.exe) (Windows 10/11). Not code-signed yet, so Windows SmartScreen asks once: *More info → Run anyway*.

## What it does

1. **Finds Star Citizen** by itself (running game, RSI Launcher files, common install folders): LIVE, PTU, EPTU, TECH-PREVIEW, HOTFIX. If it misses one, pick `StarCitizen.exe` under Settings → Game.
2. **Backs up every time the game closes.** The game writes your bindings only when it exits; 7Bind reads them a few seconds later. Identical files are never stored twice. The first backup on a new game version is always kept as a *version snapshot*. You can also press *Back up now* and give a backup a name.
3. **Never deletes a backup.** Each one is about 5 KB. They live in `%LOCALAPPDATA%\7Bind\backups` and, once you link the PC, on 7hills.space.
4. **Copies between channels**, e.g. LIVE → PTU, with a check that the game is closed.
5. **Restores** a backup, also on a new PC: pick it, check the devices, type `RESTORE`.
6. **Moves bindings to the right stick.** Windows can renumber joysticks after a reinstall or a USB change (js4 becomes js2). 7Bind matches each device by its ID and name, so your flight stick bindings stay on your flight stick. Devices that are not plugged in are skipped (or you pick another one).
7. **Bindings sheet**: a readable page of every binding per device (joysticks, panels, keyboard, mouse), with curves, inverted axes, press types (hold, double tap, modifier), buttons that do two things in red, and the defaults you removed. Print → Save as PDF; a CSV is saved next to it.

## Safety rules

- **LIVE is the template.** 7Bind only reads LIVE. The one way it ever writes to LIVE is *Restore*, after you typed `RESTORE`. Copy never targets LIVE. This is enforced in one place (`writer.py`) and covered by tests.
- **Every restore needs `RESTORE` typed**, for every channel.
- **Before 7Bind writes anything**, the target's current files are saved as a *Before restore* backup and copied raw to `%LOCALAPPDATA%\7Bind\safety` (kept 30 days).
- **Star Citizen must be closed** for copy and restore; the game rewrites these files when it exits.
- 7Bind only writes the files it manages (`actionmaps.xml`, `attributes.xml`, `attributesVR.xml`, `controls\mappings\*.xml`, `user.cfg`), inside the channel folder, atomically.
- **The website cannot make 7Bind write anything.** 7hills.space only receives uploads and serves a download when you pick a backup in 7Bind.
- `user.cfg` is merged, never replaced: the target's 7Hills Link telemetry lines always stay. 7Bind never adds telemetry lines.
- It does not read game memory, inject anything or touch Easy Anti-Cheat. It only reads and writes the game's own settings files.

## Files it backs up (per channel)

| File | What |
|---|---|
| `user\client\0\Profiles\default\actionmaps.xml` | Bindings, devices, curves, invert, press types |
| `user\client\0\Profiles\default\attributes.xml` (+ `attributesVR.xml`) | Graphics, FOV, audio, sensitivity, head tracking |
| `user\client\0\controls\mappings\*.xml` | Control profiles you exported in the game |
| `user.cfg` | Your cvars (merged on copy/restore) |

The game version comes from `BuildID` in `Profiles\defaultActions.xml` (or `build_manifest.id`).

## 7hills.space

Link the PC under Settings → Account (the same PC link as 7Hills Link; if 7Hills Link is already linked on this PC, 7Bind uses that sign-in). Backups are then uploaded and you can see, compare, export and share them on 7hills.space. The server side is described in [docs/API.md](docs/API.md). Until the site takes backups, they wait on this PC and upload later.

## Run from source

```
pip install -r requirements.txt
set PYTHONPATH=src
python -m sevenbind              # window
python -m sevenbind --backup     # back up all channels once
python -m sevenbind --headless
```

Tests: `PYTHONPATH=src:tests python -m pytest -q tests` (they use a real actionmaps.xml with 5 Virpil devices). GitHub Actions builds `7Bind.exe` on every push; every push to `main` publishes the release for the version in `src/sevenbind/__init__.py`. Updates install themselves the same way as 7Hills Link (SHA-256 checked, old exe kept until the new one starts).
