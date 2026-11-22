"""7Bind's brain: finds the game, watches it close, backs up, syncs, copies and restores.

Independent of the window so it can be tested and run headless.
"""

from __future__ import annotations

import json
import threading
import time
import webbrowser

from . import __version__, api, backup, detect, export, gamefiles, ops, updater, writer
from .paths import data_dir
from .prefs import Prefs
from .store import Store, decode

TICK = 2.0               # how often the loop looks at the game processes
SETTLE = 4.0             # wait after the game exits before reading its files
SYNC_EVERY = 60.0        # try pending uploads
MEMBER_EVERY = 300.0     # refresh who we are linked as
UPDATE_EVERY = 6 * 3600
PLAN_TTL = 1800


class Updates:
    """Looks for new releases, downloads them, installs between play sessions."""

    def __init__(self, core: "Core") -> None:
        self.core = core
        self.path = data_dir() / "update.json"
        try:
            self.auto = bool(json.loads(self.path.read_text(encoding="utf-8")).get("auto_install", True))
        except (OSError, ValueError):
            self.auto = True
        self.state = "idle"
        self.latest: str | None = None
        self.file = None
        self.error: str | None = None
        self.checked_at = 0.0
        self.install_hook = None

    def set_auto(self, on: bool) -> None:
        self.auto = bool(on)
        try:
            self.path.write_text(json.dumps({"auto_install": self.auto}), encoding="utf-8")
        except OSError:
            pass

    def check_now(self) -> None:
        self.checked_at = time.time()
        self.state, self.error = "checking", None
        try:
            info = updater.check()
            if not info:
                self.state = "up_to_date"
                return
            self.latest = info["version"]
            self.state = "downloading"
            self.file = updater.download(info)
            self.state = "ready"
        except Exception as e:
            self.state, self.error = "error", str(e)[:200]

    def tick(self) -> None:
        if not updater.can_install():
            self.state = "source"
            return
        if time.time() - self.checked_at >= UPDATE_EVERY or (self.state == "error" and time.time() - self.checked_at >= 3600):
            threading.Thread(target=self.check_now, name="update-check", daemon=True).start()
            self.checked_at = time.time()
        if self.state == "ready" and self.auto and not self.core.running and not self.core.busy:
            self.install()

    def install(self) -> None:
        if self.state != "ready" or not self.file or not self.install_hook:
            return
        self.state = "installing"
        try:
            self.install_hook(self.file)
        except Exception as e:
            self.state, self.error = "error", str(e)[:200]

    def status(self) -> dict:
        return {"state": self.state, "latest": self.latest, "error": self.error, "auto": self.auto,
                "can_install": updater.can_install()}


class Core:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.store = Store()
        self.prefs = Prefs()
        self.updates = Updates(self)
        self.installs: list[detect.Install] = []
        self.running: set[str] = set()          # channels whose StarCitizen.exe runs now
        self.pending: dict[str, float] = {}     # channel -> time it closed (backup due)
        self.busy = False
        self.events: list[dict] = []            # Recent
        self.game_path_file = data_dir() / "game.json"
        try:
            gp = json.loads(self.game_path_file.read_text(encoding="utf-8")).get("paths") or {}
        except (OSError, ValueError, AttributeError):
            gp = {}
        self.game_paths: dict[str, str] = {str(k): str(v) for k, v in gp.items()} if isinstance(gp, dict) else {}
        self.token, self.token_source = api.load_token()
        self.member: dict | None = None
        self.link: dict | None = None
        self.link_error: str | None = None
        self.cloud_state = "off"                # off | ok | unavailable | error
        self.cloud_error: str | None = None
        self.plans: dict[str, ops.Plan] = {}
        self._last_sync = 0.0
        self._last_member = 0.0
        self._stop = threading.Event()

    # ---------------------------------------------------------------- helpers

    def log(self, text: str) -> None:
        with self.lock:
            self.events.insert(0, {"at": time.strftime("%d %b %H:%M"), "text": text})
            del self.events[30:]

    def install(self, channel: str) -> detect.Install | None:
        return next((i for i in self.installs if i.channel == str(channel).upper()), None)

    def scan(self) -> None:
        installs = detect.apply_choices(detect.find_installs(), self.game_paths)
        with self.lock:
            self.installs = installs

    def set_game_path(self, channel: str, exe: str | None) -> str | None:
        channel = str(channel).upper()
        if exe:
            inst = detect.install_from_exe(exe)
            if inst is None:
                return "Pick StarCitizen.exe inside a Bin64 folder"
            if inst.channel != channel:
                return f"That exe is in the {inst.channel} folder, not {channel}"
            self.game_paths[channel] = str(inst.exe)
        else:
            self.game_paths.pop(channel, None)
        try:
            self.game_path_file.write_text(json.dumps({"paths": self.game_paths}), encoding="utf-8")
        except OSError:
            pass
        self.scan()
        return None

    # ---------------------------------------------------------------- backups

    def backup(self, channel: str, kind: str = "auto", name: str | None = None, force: bool = False) -> dict:
        inst = self.install(channel)
        if not inst:
            return {"result": "missing", "backup": None}
        r = backup.backup_channel(self.store, inst.channel, inst.folder, kind=kind, name=name, force=force)
        if r["result"] == "saved":
            b = r["backup"]
            what = backup.describe(b)
            self.log(f"{inst.channel} backed up · {what}" if b.get("kind") != "version_snapshot"
                     else f"{inst.channel} {b.get('game_version') or ''} found · version snapshot saved")
            self._last_sync = 0   # upload soon
        return r

    def backup_all(self, name: str | None = None, force: bool = False) -> list[dict]:
        out = []
        for inst in list(self.installs):
            if inst.channel in self.running:
                continue
            kind = "manual" if (force or name) else "auto"
            out.append({"channel": inst.channel, **self.backup(inst.channel, kind, name, force)})
        return out

    def _watch(self) -> None:
        now_running = {f.name.upper() for f in detect.running_game_folders()}
        with self.lock:
            for ch in self.running - now_running:
                self.pending[ch] = time.time()
                self.log(f"Star Citizen {ch} closed")
            for ch in now_running - self.running:
                self.log(f"Star Citizen {ch} started")
            self.running = now_running
            due = [ch for ch, t in self.pending.items() if time.time() - t >= SETTLE and ch not in self.running]
            for ch in due:
                self.pending.pop(ch, None)
        if self.prefs.get("auto_backup"):
            for ch in due:
                try:
                    self.backup(ch)
                except Exception as e:
                    self.log(f"{ch} backup failed: {str(e)[:80]}")

    # ---------------------------------------------------------------- cloud

    def _sync(self) -> None:
        if not self.token or not self.prefs.get("cloud"):
            self.cloud_state = "off"
            return
        for meta in self.store.pending_upload():
            try:
                r = api.upload_backup(self.token, meta, self.store.blob(meta["id"]))
                self.store.update(meta["id"], cloud={"id": r.get("id") or meta["id"], "at": time.time()})
                self.cloud_state, self.cloud_error = "ok", None
            except api.ApiError as e:
                if e.status == 401:
                    self._lost_key()
                elif e.status in (404, 405, 501):
                    self.cloud_state, self.cloud_error = "unavailable", "7hills.space does not take backups yet. They are kept on this PC and sent later."
                else:
                    self.cloud_state, self.cloud_error = "error", e.message[:160]
                return
            except OSError as e:
                self.cloud_error = str(e)[:160]
                return
        if self.cloud_state == "off":
            self.cloud_state = "ok"

    def cloud_list(self, channel: str | None = None) -> list[dict]:
        if not self.token:
            return []
        try:
            items = api.list_backups(self.token, channel)
        except api.ApiError:
            return []
        local = {m.get("id") for m in self.store.list()}
        for it in items:
            it["local"] = it.get("id") in local
        return items

    def fetch_cloud(self, cloud_id: str) -> dict:
        blob = api.download_backup(self.token, cloud_id)
        meta = self.store.add_blob(blob)
        self.store.update(meta["id"], cloud={"id": cloud_id, "at": time.time()})
        return meta

    # ---------------------------------------------------------------- linking

    def start_link(self) -> None:
        try:
            self.link = api.start_link()
            self.link_error = None
            webbrowser.open(self.link["url"])
            threading.Thread(target=self._poll_link, name="link-poll", daemon=True).start()
        except api.ApiError as e:
            self.link_error = e.message

    def _poll_link(self) -> None:
        link = self.link
        deadline = time.time() + (link or {}).get("expires_in", 600)
        while link and time.time() < deadline and not self._stop.is_set():
            try:
                r = api.poll_link(link["code"], link["poll_secret"])
                if r.get("status") == "linked" and r.get("token"):
                    api.save_token(r["token"])
                    api.set_signed_out(False)
                    with self.lock:
                        self.token, self.token_source, self.link = r["token"], "7bind", None
                    self._refresh_member(force=True)
                    self._last_sync = 0
                    return
            except api.ApiError as e:
                if e.status in (404, 410):
                    self.link_error, self.link = "The code expired. Start again.", None
                    return
            time.sleep(2)
        if self.link is link:
            self.link, self.link_error = None, "The code expired. Start again."

    def unlink(self) -> None:
        """Sign 7Bind out. 7Hills Link's own key is left alone and not picked up again."""
        api.clear_token()
        api.set_signed_out(True)
        with self.lock:
            self.token, self.token_source, self.member = None, "", None
        self.cloud_state = "off"

    def _lost_key(self) -> None:
        if self.token_source == "7bind":
            api.clear_token()
        self.token, self.token_source, self.member = None, "", None
        self.link_error = "This PC was unlinked on 7Net. Link it again."

    def _refresh_member(self, force: bool = False) -> None:
        if not self.token or (not force and time.time() - self._last_member < MEMBER_EVERY):
            return
        self._last_member = time.time()
        try:
            self.member = api.whoami(self.token).get("member")
        except api.ApiError as e:
            if e.status == 401:
                self._lost_key()

    # ---------------------------------------------------------------- copy / restore

    def plan_copy(self, source: str, target: str, groups: list[str]) -> dict:
        s, t = self.install(source), self.install(target)
        if not s or not t:
            raise ops.OpError("Channel not installed")
        files = gamefiles.read_channel(s.folder)
        if not files:
            raise ops.OpError(f"{s.channel} has no settings to copy yet. Start the game once.")
        plan = ops.make_plan("copy", f"{s.channel} (now)", s.channel, files, t, self.installs, groups)
        return self._keep(plan)

    def plan_restore(self, backup_id: str, target: str, groups: list[str]) -> dict:
        t = self.install(target)
        meta = self.store.get(backup_id)
        if not t or not meta:
            raise ops.OpError("Backup or channel not found")
        files = self.store.files(backup_id)
        label = meta.get("name") or {"version_snapshot": "Version snapshot", "before_restore": "Before restore"}.get(meta.get("kind"), "Automatic")
        plan = ops.make_plan("restore", f"{label} · {meta.get('channel')} · {meta.get('created_at', '')[:16].replace('T', ' ')}",
                             meta.get("channel", ""), files, t, self.installs, groups, backup_id)
        return self._keep(plan)

    def _keep(self, plan: ops.Plan) -> dict:
        now = time.time()
        with self.lock:
            for k in [k for k, p in self.plans.items() if now - p.created > PLAN_TTL]:
                self.plans.pop(k, None)
            self.plans[plan.id] = plan
        return plan.as_dict()

    def set_override(self, plan_id: str, source_instance: int, target_instance) -> dict:
        plan = self.plans[plan_id]
        plan.overrides[int(source_instance)] = None if target_instance in (None, "", "skip") else int(target_instance)
        return plan.as_dict()

    def run_plan(self, plan_id: str, typed: str | None = None) -> dict:
        plan = self.plans.get(plan_id)
        if not plan:
            raise ops.OpError("This step expired. Start again.")
        confirmation = None
        if plan.mode == "restore":
            confirmation = writer.confirm(typed or "", plan.target_channel)
        self.busy = True
        try:
            r = ops.execute(plan, self.store, confirmation)
        finally:
            self.busy = False
        self.plans.pop(plan_id, None)
        verb = "Copied" if plan.mode == "copy" else "Restored"
        self.log(f"{verb} {plan.source_label} into {plan.target_channel}")
        self._last_sync = 0
        return r

    # ---------------------------------------------------------------- export

    def export_sheet(self, backup_id: str | None, channel: str | None = None) -> dict:
        if backup_id:
            meta = self.store.get(backup_id)
            files = self.store.files(backup_id)
        else:
            inst = self.install(channel or "LIVE")
            if not inst:
                raise ops.OpError("Channel not installed")
            from . import version
            v = version.game_build(inst.folder)
            meta = {"channel": inst.channel, "game_version": v["version"], "game_build": v["build"],
                    "created_at": time.strftime("%Y-%m-%dT%H:%M")}
            files = gamefiles.read_channel(inst.folder)
        owner = (self.member or {}).get("handle")
        out = export.write_exports(files, meta or {}, owner)
        export.open_path(out["html"])
        return out

    # ---------------------------------------------------------------- loop

    def run(self) -> None:
        self.scan()
        self.running = {f.name.upper() for f in detect.running_game_folders()}
        self._refresh_member(force=True)
        # Catch up on anything that changed while 7Bind was not running.
        if self.prefs.get("auto_backup"):
            for inst in list(self.installs):
                if inst.channel not in self.running:
                    try:
                        self.backup(inst.channel)
                    except Exception as e:
                        self.log(f"{inst.channel} backup failed: {str(e)[:80]}")
        last_scan = time.time()
        while not self._stop.is_set():
            self._stop.wait(TICK)
            try:
                if time.time() - last_scan > 60:
                    self.scan()
                    last_scan = time.time()
                self._watch()
                self._refresh_member()
                if time.time() - self._last_sync >= SYNC_EVERY:
                    self._last_sync = time.time()
                    self._sync()
                self.updates.tick()
            except Exception as e:   # the loop must survive anything
                self.log(f"Error: {str(e)[:100]}")

    def stop(self) -> None:
        self._stop.set()

    # ---------------------------------------------------------------- status

    def channel_cards(self) -> list[dict]:
        out = []
        by = {i.channel: i for i in self.installs}
        for ch in detect.CHANNELS:
            inst = by.get(ch)
            latest = self.store.latest(ch)
            item = {"channel": ch, "installed": inst is not None, "running": ch in self.running,
                    "template": ch == "LIVE", "latest": latest}
            if inst:
                from . import version
                item["game"] = version.game_build(inst.folder)
                item["path"] = str(inst.folder)
            out.append(item)
        return out

    def status(self) -> dict:
        with self.lock:
            backups = self.store.list()
            return {
                "version": __version__,
                "update": self.updates.status(),
                "prefs": self.prefs.as_dict(),
                "can_autostart": updater.can_install(),
                "installs": [i.as_dict() for i in self.installs],
                "channels": self.channel_cards(),
                "running": sorted(self.running),
                "busy": self.busy,
                "linked": bool(self.token),
                "token_source": self.token_source,
                "member": self.member,
                "link": {"code": self.link["code"], "url": self.link["url"]} if self.link else None,
                "link_error": self.link_error,
                "cloud": {"state": self.cloud_state, "error": self.cloud_error,
                          "pending": len(self.store.pending_upload())},
                "backups": [dict(m, what=backup.describe(m)) for m in backups[:200]],
                "backup_count": len(backups),
                "events": self.events[:8],
                "groups": gamefiles.GROUPS,
            }


def bundle_meta(blob: bytes) -> dict:
    return decode(blob)[0]
