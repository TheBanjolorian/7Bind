import pytest

from sevenbind import usercfg, writer
from conftest import fixture_bytes

AM = "user/client/0/Profiles/default/actionmaps.xml"


def test_live_refuses_without_restore(game):
    with pytest.raises(writer.Refused):
        writer.write_files(game["LIVE"], {AM: b"<ActionMaps/>"})
    assert (game["LIVE"] / AM).read_bytes() == fixture_bytes("live_actionmaps.xml")


def test_live_needs_exact_word_and_channel(game):
    with pytest.raises(writer.Refused):
        writer.confirm("restore", "LIVE")
    with pytest.raises(writer.Refused):
        writer.confirm("RESTORE ", "LIVE")
    c = writer.confirm("RESTORE", "PTU")
    with pytest.raises(writer.Refused):
        writer.write_files(game["LIVE"], {AM: b"<ActionMaps/>"}, confirmation=c)
    with pytest.raises(writer.Refused):
        writer.Confirmation(object(), "LIVE")


def test_live_restore_with_confirmation_is_single_use(game):
    c = writer.confirm("RESTORE", "LIVE")
    writer.write_files(game["LIVE"], {AM: b"<ActionMaps/>\n"}, confirmation=c)
    assert (game["LIVE"] / AM).read_bytes() == b"<ActionMaps/>\n"
    with pytest.raises(writer.Refused):
        writer.write_files(game["LIVE"], {AM: b"x"}, confirmation=c)


def test_only_managed_paths(game):
    for rel in ["../LIVE/user.cfg", "Bin64/StarCitizen.exe", "user/client/0/Profiles/default/../../x.xml",
                "C:/Windows/x.xml", "user/client/0/Profiles/default/other.xml", "user\\cfg"]:
        with pytest.raises(writer.Refused):
            writer.write_files(game["PTU"], {rel: b"x"})


def test_copy_target_ptu_needs_no_word(game):
    writer.write_files(game["PTU"], {AM: b"<ActionMaps/>\n"})
    assert (game["PTU"] / AM).read_bytes() == b"<ActionMaps/>\n"


def test_user_cfg_merge_keeps_target_link_lines():
    src = "r_DisplayInfo = 1\nsys_maxfps = 144\ngrpc.client.server.port = 1\n"
    tgt = fixture_bytes("ptu_user.cfg").decode()
    out = usercfg.merge(src, tgt)
    assert "sys_maxfps = 144" in out and "r_DisplayInfo = 1" in out
    assert "grpc.client.server.port = 50051" in out
    assert "grpc.client.server.port = 1" not in out
    assert "server.game.telemetry.stream.interval.ms = 50" in out
    assert "-- 7Hills Link: game telemetry for 7Net" in out


def test_user_cfg_merge_no_link_in_target():
    out = usercfg.merge(fixture_bytes("live_user.cfg").decode() + "sys_maxfps = 60\n", "")
    assert out == "sys_maxfps = 60\n"
