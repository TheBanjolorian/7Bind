import pytest

from sevenbind import backup, detect, export, gamefiles, ops, writer
from sevenbind.store import Store
from conftest import fixture_bytes

AM = gamefiles.ACTIONMAPS
ATTR = gamefiles.ATTRIBUTES


def installs(game):
    return detect.channels_in(game["root"])


def inst(game, ch):
    return next(i for i in installs(game) if i.channel == ch)


def test_backup_dedupe_changes_and_version_snapshot(home, game):
    s = Store()
    r1 = backup.backup_channel(s, "LIVE", game["LIVE"])
    assert r1["result"] == "saved" and r1["backup"]["game_version"] == "4.10"
    assert r1["backup"]["summary"]["bindings"] == 60
    assert backup.describe(r1["backup"]) == "First backup"
    assert backup.backup_channel(s, "LIVE", game["LIVE"])["result"] == "unchanged"
    p = game["LIVE"] / ATTR
    p.write_text(p.read_text().replace('name="FOV" value="83.9863"', 'name="FOV" value="90"'))
    r3 = backup.backup_channel(s, "LIVE", game["LIVE"])
    assert r3["result"] == "saved"
    assert "Field of view" in r3["backup"]["changes"]["settings_changed"]
    da = game["LIVE"] / "user/client/0/Profiles/defaultActions.xml"
    da.write_text(da.read_text().replace("4.10.201.48085", "4.11.100.1"))
    r4 = backup.backup_channel(s, "LIVE", game["LIVE"])
    assert r4["result"] == "saved" and r4["backup"]["kind"] == "version_snapshot" and r4["backup"]["pinned"]
    assert len(s.list("LIVE")) == 3
    # index survives being lost
    s.index_path.unlink()
    assert len(Store().list("LIVE")) == 3


def test_copy_live_to_ptu_never_touches_live(home, game):
    s = Store()
    before_live = fixture_bytes("live_actionmaps.xml")
    plan = ops.make_plan("copy", "LIVE (now)", "LIVE", gamefiles.read_channel(game["LIVE"]),
                         inst(game, "PTU"), installs(game), ["bindings", "settings"])
    d = plan.as_dict()
    assert all(x["status"] == "same" for x in d["devices"])
    r = ops.execute(plan, s)
    assert AM in r["written"] and ATTR in r["written"]
    assert (game["PTU"] / AM).read_bytes().count(b"rebind") >= 60
    assert (game["LIVE"] / AM).read_bytes() == before_live
    assert s.get(r["before_restore"])["kind"] == "before_restore"
    assert s.get(r["before_restore"])["channel"] == "PTU"


def test_copy_into_live_refused(home, game):
    with pytest.raises(ops.OpError):
        ops.make_plan("copy", "PTU", "PTU", gamefiles.read_channel(game["PTU"]), inst(game, "LIVE"), installs(game), ["bindings"])


def test_restore_needs_restore_word(home, game):
    s = Store()
    b = backup.backup_channel(s, "PTU", game["PTU"])["backup"]
    plan = ops.make_plan("restore", "x", "PTU", s.files(b["id"]), inst(game, "LIVE"), installs(game), ["bindings"], b["id"])
    with pytest.raises(ops.OpError):
        ops.execute(plan, s)
    with pytest.raises(writer.Refused):
        writer.confirm("Restore", "LIVE")
    r = ops.execute(plan, s, writer.confirm("RESTORE", "LIVE"))
    assert r["written"] == [AM]
    assert s.get(r["before_restore"])["summary"]["bindings"] == 60   # LIVE kept as a backup first


def test_user_cfg_copy_keeps_target_link_block(home, game):
    s = Store()
    plan = ops.make_plan("copy", "LIVE", "LIVE", {gamefiles.USER_CFG: b"sys_maxfps = 120\n"},
                         inst(game, "PTU"), installs(game), ["user_cfg"])
    ops.execute(plan, s)
    out = (game["PTU"] / "user.cfg").read_text()
    assert "sys_maxfps = 120" in out and "grpc.client.server.port = 50051" in out


def test_export_sheet(home, game):
    files = gamefiles.read_channel(game["LIVE"])
    html = export.html_sheet(files, {"channel": "LIVE", "game_version": "4.10"}, "Banjo")
    assert "VPC Panel #1" in html and "RIGHT VPC Stick WarBRD" in html and "Flight ready" in html
    assert "do two things" in html and "removed by you" in html
    assert "inverted" in html and "curve" in html
    csv = export.csv_text(files)
    assert csv.count("\n") == 1 + 82
