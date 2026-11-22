import shutil
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
PROFILE = "user/client/0/Profiles/default"


def make_channel(root: Path, channel: str, actionmaps: str | None, attributes: str | None = None,
                 user_cfg: str | None = None, build: str = "4.10.201.48085") -> Path:
    ch = root / channel
    (ch / "Bin64").mkdir(parents=True, exist_ok=True)
    (ch / "Bin64" / "StarCitizen.exe").write_bytes(b"")
    prof = ch / PROFILE
    prof.mkdir(parents=True, exist_ok=True)
    if actionmaps:
        shutil.copy(FIX / actionmaps, prof / "actionmaps.xml")
    if attributes:
        shutil.copy(FIX / attributes, prof / "attributes.xml")
    if user_cfg:
        shutil.copy(FIX / user_cfg, ch / "user.cfg")
    (ch / "user/client/0/Profiles/defaultActions.xml").write_text(
        f'<DefaultActions VersionID="7" BuildID="{build}">\n</DefaultActions>\n')
    return ch


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "appdata"
    monkeypatch.setenv("SEVENBIND_HOME", str(h))
    return h


@pytest.fixture
def game(tmp_path):
    root = tmp_path / "StarCitizen"
    live = make_channel(root, "LIVE", "live_actionmaps.xml", "live_attributes.xml", "live_user.cfg")
    ptu = make_channel(root, "PTU", "ptu_actionmaps.xml", "ptu_attributes.xml", "ptu_user.cfg", build="5.0.202.10025")
    return {"root": root, "LIVE": live, "PTU": ptu}


def fixture_bytes(name: str) -> bytes:
    return (FIX / name).read_bytes()
