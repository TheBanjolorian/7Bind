"""The window (pywebview + one local HTML page in 7Net's look)."""

from __future__ import annotations

import os
import threading
import webbrowser

from . import ops, updater, writer
from .core import Core
from .paths import resource, sub
from .prefs import DEFAULTS, apply_startup

SITE = "https://www.7hills.space"
WEB_PAGES = {"backups": "/settings/game-backups", "link": "/link", "site": "",
             "github": None}
GITHUB = "https://github.com/TheBanjolorian/7Bind"


def _safe(fn):
    """Return {"error": text} instead of raising into the page."""
    def wrap(*a, **k):
        try:
            return fn(*a, **k)
        except (ops.OpError, writer.Refused) as e:
            return {"error": str(e)}
        except Exception as e:  # noqa: BLE001 - show it, never crash the window
            return {"error": f"Something went wrong: {str(e)[:200]}"}
    wrap.__name__ = fn.__name__
    return wrap


class JsApi:
    """Methods the page calls through window.pywebview.api."""

    def __init__(self, core: Core, autostart: bool):
        self._core = core
        self._autostart = autostart
        self._window = None
        self._quit = None
        self._path_error: str | None = None

    def status(self):
        s = self._core.status()
        s["autostarted"] = self._autostart
        s["path_error"] = self._path_error
        return s

    # ------------------------------------------------------------ backups
    @_safe
    def backup_now(self, name=None):
        name = (str(name).strip() if name else "") or None
        results = self._core.backup_all(name=name, force=False)
        return {"results": results, "status": self.status()}

    @_safe
    def rename(self, backup_id, name):
        self._core.store.update(str(backup_id), name=str(name).strip()[:60] or None)
        return self.status()

    @_safe
    def backup_files(self, backup_id):
        m = self._core.store.get(str(backup_id))
        return {"meta": m}

    @_safe
    def export_sheet(self, backup_id=None, channel=None):
        return self._core.export_sheet(str(backup_id) if backup_id else None, channel)

    @_safe
    def cloud_list(self, channel=None):
        return {"backups": self._core.cloud_list(channel)}

    @_safe
    def fetch_cloud(self, cloud_id):
        return {"backup": self._core.fetch_cloud(str(cloud_id))}

    # ------------------------------------------------------------ copy / restore
    @_safe
    def plan_copy(self, source, target, groups):
        return self._core.plan_copy(str(source), str(target), list(groups or []))

    @_safe
    def plan_restore(self, backup_id, target, groups):
        return self._core.plan_restore(str(backup_id), str(target), list(groups or []))

    @_safe
    def set_override(self, plan_id, source_instance, target_instance):
        return self._core.set_override(str(plan_id), int(source_instance), target_instance)

    @_safe
    def run_plan(self, plan_id, typed=None):
        r = self._core.run_plan(str(plan_id), typed)
        return {"ok": True, "result": r, "status": self.status()}

    # ------------------------------------------------------------ account
    def start_link(self):
        self._core.start_link()
        return self.status()

    def open_link_page(self):
        link = self._core.link
        webbrowser.open(link["url"] if link else SITE + "/link")

    def unlink(self):
        self._core.unlink()
        return self.status()

    # ------------------------------------------------------------ game folders
    def rescan(self):
        self._core.scan()
        return self.status()

    def browse_game(self, channel):
        import webview
        start = ""
        inst = self._core.install(str(channel))
        if inst:
            start = str(inst.exe.parent)
        picked = self._window.create_file_dialog(webview.OPEN_DIALOG, directory=start, allow_multiple=False,
                                                 file_types=("Programs (*.exe)",))
        if picked:
            path = picked[0] if isinstance(picked, (list, tuple)) else picked
            self._path_error = self._core.set_game_path(str(channel), str(path))
        return self.status()

    def reset_game_path(self, channel):
        self._path_error = self._core.set_game_path(str(channel), None)
        return self.status()

    # ------------------------------------------------------------ app
    def set_pref(self, key, value):
        if str(key) in DEFAULTS:
            self._core.prefs.set(str(key), bool(value))
            if str(key) == "cloud":
                self._core._last_sync = 0
        return self.status()

    def update_now(self):
        self._core.updates.install()
        return self.status()

    def check_updates(self):
        self._core.updates.check_now()
        return self.status()

    def set_auto_update(self, on):
        self._core.updates.set_auto(bool(on))
        return self.status()

    def open_web(self, key):
        if str(key) == "github":
            webbrowser.open(GITHUB)
            return
        path = WEB_PAGES.get(str(key))
        if path is not None:
            webbrowser.open(SITE + path)

    def quit(self):
        """Stop 7Bind completely (window, tray and backups)."""
        if self._quit:
            threading.Thread(target=self._quit, name="quit", daemon=True).start()

    def open_folder(self, which="backups"):
        folder = sub("backups" if which == "backups" else "exports")
        if os.name == "nt":
            os.startfile(str(folder))   # type: ignore[attr-defined]
        else:
            webbrowser.open(folder.as_uri())


def run_window(updated_from: str | None = None, autostart: bool = False) -> int:
    import webview  # pywebview

    core = Core()
    apply_startup(core.prefs.get("start_with_windows"))
    page = str(resource("ui", "index.html"))
    js_api = JsApi(core, autostart)
    window = webview.create_window("7Bind", url=page, js_api=js_api, width=1060, height=740,
                                   min_size=(860, 600), background_color="#0A0A0A", hidden=autostart)
    js_api._window = window

    from .tray import Tray

    quitting = threading.Event()

    def show_window():
        try:
            window.show()
            window.restore()
        except Exception:
            pass

    def quit_app():
        quitting.set()
        tray.stop()
        core.stop()
        try:
            window.destroy()
        except Exception:
            os._exit(0)

    def backup_now():
        threading.Thread(target=core.backup_all, name="backup-now", daemon=True).start()

    tray = Tray(show_window, backup_now, quit_app)
    js_api._quit = quit_app

    from . import single
    single.listen(show_window, quit_app)

    def to_tray() -> bool:
        return tray.available and core.prefs.get("tray") and not quitting.is_set()

    def on_minimized(*_):
        if to_tray():
            window.hide()

    def on_closing(*_):
        if to_tray():
            window.hide()
            return False
        return True

    window.events.minimized += on_minimized
    window.events.closing += on_closing

    def install(new_exe):
        if updater.install(new_exe):
            quitting.set()
            tray.stop()
            core.stop()
            try:
                window.destroy()
            finally:
                os._exit(0)
    core.updates.install_hook = install

    def tray_title_loop():
        while not quitting.is_set():
            try:
                st = core.status()
                running = ", ".join(st.get("running") or []) or "game not running"
                tray.set_title(f"7Bind {st.get('version')} · {st.get('backup_count')} backups · {running}")
            except Exception:
                pass
            quitting.wait(10)

    def started():
        threading.Thread(target=core.run, name="core", daemon=True).start()
        tray.start()
        if autostart and not tray.available:
            show_window()
        threading.Thread(target=tray_title_loop, name="tray-title", daemon=True).start()
        if updated_from:
            threading.Thread(target=updater.cleanup, name="update-cleanup", daemon=True).start()

    webview.start(started, http_server=True)
    tray.stop()
    core.stop()
    return 0
