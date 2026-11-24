import json

from sevenbind import api, core as core_mod, detect, export
from sevenbind.app import JsApi


def make_core(game, monkeypatch):
    monkeypatch.setattr(detect, "find_installs", lambda extra_roots=None: detect.channels_in(game["root"]))
    monkeypatch.setattr(detect, "running_game_folders", lambda: [])
    monkeypatch.setattr(api, "load_token", lambda: (None, ""))
    monkeypatch.setattr(export, "open_path", lambda p: None)
    c = core_mod.Core()
    c.scan()
    return c


def test_window_api_flow(home, game, monkeypatch):
    c = make_core(game, monkeypatch)
    js = JsApi(c, autostart=False)
    s = js.status()
    json.dumps(s)   # the page receives it as JSON
    assert [x["channel"] for x in s["channels"] if x["installed"]] == ["LIVE", "PTU"]

    r = js.backup_now("Before 5.0")
    assert {x["channel"]: x["result"] for x in r["results"]} == {"LIVE": "saved", "PTU": "saved"}
    live_b = next(b for b in r["status"]["backups"] if b["channel"] == "LIVE")
    assert live_b["name"] == "Before 5.0" and live_b["kind"] == "named" and live_b["pinned"]
    assert js.backup_now(None)["results"][0]["result"] == "unchanged"

    # Copy into LIVE is refused at planning time.
    assert "error" in js.plan_copy("PTU", "LIVE", ["bindings"])
    p = js.plan_copy("LIVE", "PTU", ["bindings"])
    assert p["target"] == "PTU" and not p["game_running"]
    out = js.run_plan(p["id"])
    assert out["ok"]

    # Restore into LIVE needs RESTORE.
    p2 = js.plan_restore(live_b["id"], "LIVE", ["bindings", "settings"])
    assert p2["target_is_live"]
    assert "error" in js.run_plan(p2["id"], "restore")
    p2 = js.plan_restore(live_b["id"], "LIVE", ["bindings", "settings"])
    done = js.run_plan(p2["id"], "RESTORE")
    assert done["ok"], done
    kinds = [b["kind"] for b in done["status"]["backups"]]
    assert kinds.count("before_restore") == 2   # PTU before the copy, LIVE before the restore

    sheet = js.export_sheet(live_b["id"])
    assert sheet["html"].endswith(".html")


def test_watch_backs_up_after_game_closes(home, game, monkeypatch):
    c = make_core(game, monkeypatch)
    c.running = {"LIVE"}
    monkeypatch.setattr(core_mod, "SETTLE", 0)
    c._watch()          # LIVE no longer running -> pending, then due
    c._watch()
    assert c.store.latest("LIVE") is not None
    assert any("closed" in e["text"] for e in c.events)


def _signed_in(game, monkeypatch, source):
    c = make_core(game, monkeypatch)
    calls = []
    monkeypatch.setattr(api, "clear_token", lambda: calls.append("forget own key"))
    c.token, c.token_source = "7hl_test", source
    return c, calls


def test_sign_out_unlinks_7binds_own_key_on_7net_first(home, game, monkeypatch):
    c, calls = _signed_in(game, monkeypatch, "7bind")
    monkeypatch.setattr(api, "unlink_device", lambda token: calls.append("unlink " + token) or {"ok": True})
    c.unlink()
    assert calls == ["unlink 7hl_test", "forget own key"]
    assert c.token is None and c.link_error is None and api.signed_out()


def test_sign_out_leaves_a_borrowed_7hills_link_key_alone(home, game, monkeypatch):
    c, calls = _signed_in(game, monkeypatch, "7hills-link")
    monkeypatch.setattr(api, "unlink_device", lambda token: calls.append("unlink") or {"ok": True})
    c.unlink()
    assert "unlink" not in calls and c.token is None and api.signed_out()


def test_sign_out_without_7net_says_so(home, game, monkeypatch):
    c, calls = _signed_in(game, monkeypatch, "7bind")
    def down(token):
        raise api.ApiError(0, "timed out")
    monkeypatch.setattr(api, "unlink_device", down)
    c.unlink()
    assert c.token is None and c.link_error == core_mod.UNLINK_UNCONFIRMED


def test_refused_key_says_why(home, game, monkeypatch):
    c, calls = _signed_in(game, monkeypatch, "7bind")
    for (code, reason), text in [(("expired", None), "90 days"), (("unlinked", "admin"), "An admin unlinked"),
                                 (("unlinked", "limit"), "you can have 5"), (("unlinked", "user"), "unlinked on 7Net")]:
        c.token, c.token_source = "7hl_test", "7bind"
        def refuse(token, code=code, reason=reason):
            raise api.ApiError(401, "refused", code, reason)
        monkeypatch.setattr(api, "whoami", refuse)
        c._refresh_member(force=True)
        assert c.token is None and text in c.link_error, (code, reason, c.link_error)


def test_link_start_sends_7binds_own_install_id(home, monkeypatch):
    seen = {}
    monkeypatch.setattr(api, "_json", lambda method, path, body=None, token=None: seen.update(path=path, body=body) or {})
    api.start_link()
    first = seen["body"]["install_id"]
    api.start_link()
    assert seen["path"] == "/api/telemetry/link/start" and seen["body"]["install_id"] == first
    assert (home / "install.id").read_text().strip() == first
