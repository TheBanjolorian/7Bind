"""Moves bindings to the right physical device when Windows renumbers joysticks.

Devices are matched by GUID, then by exact name. The result maps each joystick
instance in the backup to the instance the same device has on this PC (or None
when it is not here; its bindings are then skipped unless the player picks one).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .actionmaps import Device, Profile, _INPUT_RE


@dataclass
class Match:
    source: Device
    target: Device | None
    how: str            # guid | name | none

    @property
    def status(self) -> str:
        if self.target is None:
            return "missing"
        return "same" if self.target.instance == self.source.instance else "moved"

    def as_dict(self, bindings: int = 0) -> dict:
        return {"name": self.source.name, "guid": self.source.guid, "from": self.source.instance,
                "to": self.target.instance if self.target else None, "status": self.status,
                "how": self.how, "bindings": bindings, "curves": len(self.source.curves)}


def match_devices(src: Profile, dst_devices: list[Device]) -> list[Match]:
    targets = [d for d in dst_devices if d.kind == "joystick" and d.product]
    used: set[int] = set()
    out: list[Match] = []
    for s in src.joysticks:
        t = None
        how = "none"
        if s.guid:
            same = [d for d in targets if d.guid == s.guid and d.instance not in used]
            if len(same) == 1 or (same and s.name):
                byname = [d for d in same if d.name == s.name]
                t = (byname or same)[0]
                how = "guid"
        if t is None and s.name:
            same = [d for d in targets if d.name == s.name and d.instance not in used]
            if same:
                t, how = same[0], "name"
        if t is not None:
            used.add(t.instance)
        out.append(Match(s, t, how))
    return out


def mapping_from(matches: list[Match], overrides: dict[int, int | None] | None = None) -> dict[int, int | None]:
    m = {x.source.instance: (x.target.instance if x.target else None) for x in matches}
    for k, v in (overrides or {}).items():
        m[int(k)] = None if v in (None, "", "skip") else int(v)
    return m


def apply(xml: bytes, mapping: dict[int, int | None], target_devices: list[Device] | None = None) -> tuple[bytes, dict]:
    """Rewrite joystick instances in actionmaps.xml.

    Instances mapped to None lose their bindings and their <options> block.
    Joystick <options> for devices on this PC that the backup does not mention
    are added back from target_devices (product only), so the game keeps them.
    Returns (new xml, stats).
    """
    root = ET.fromstring(xml)
    prof = root.find("ActionProfiles")
    if prof is None:
        prof = root
    stats = {"skipped": 0, "moved": 0}

    def new_inst(i: int) -> int | None:
        return mapping.get(i, i)

    for opt in list(prof.findall("options")):
        if (opt.get("type") or "").lower() != "joystick":
            continue
        try:
            i = int(opt.get("instance") or "0")
        except ValueError:
            continue
        if not opt.get("Product"):
            prof.remove(opt)          # empty slot placeholders; re-added below
            continue
        n = new_inst(i)
        if n is None:
            prof.remove(opt)
        else:
            opt.set("instance", str(n))

    for am in prof.findall("actionmap"):
        for action in list(am.findall("action")):
            for rb in list(action.findall("rebind")):
                m = _INPUT_RE.match(rb.get("input") or "")
                if not m or m.group(1).lower() != "js":
                    continue
                i = int(m.group(2))
                n = new_inst(i)
                if n is None:
                    action.remove(rb)
                    stats["skipped"] += 1
                elif n != i:
                    rb.set("input", f"js{n}_{m.group(3)}")
                    stats["moved"] += 1
            if len(action.findall("rebind")) == 0:
                am.remove(action)
        if len(am.findall("action")) == 0:
            prof.remove(am)

    # Devices on this PC that the backup did not have: keep their slot listed.
    have = {int(o.get("instance")) for o in prof.findall("options")
            if (o.get("type") or "").lower() == "joystick" and (o.get("instance") or "").isdigit()}
    insert_at = _options_end(prof)
    for d in target_devices or []:
        if d.kind == "joystick" and d.product and d.instance not in have:
            el = ET.Element("options", {"type": "joystick", "instance": str(d.instance), "Product": d.product})
            prof.insert(insert_at, el)
            insert_at += 1
            have.add(d.instance)
    # Empty slots up to 8, as the game writes them.
    for i in range(1, 9):
        if i not in have:
            prof.insert(insert_at, ET.Element("options", {"type": "joystick", "instance": str(i)}))
            insert_at += 1
    _sort_joystick_options(prof)
    ET.indent(root, space=" ")
    return ET.tostring(root, encoding="unicode").encode("utf-8") + b"\n", stats


def _options_end(prof: ET.Element) -> int:
    last = -1
    for idx, child in enumerate(list(prof)):
        if child.tag in ("options", "deviceoptions"):
            last = idx
    return last + 1


def _sort_joystick_options(prof: ET.Element) -> None:
    children = list(prof)
    js = [c for c in children if c.tag == "options" and (c.get("type") or "").lower() == "joystick"]
    if not js:
        return
    first = children.index(js[0])
    for c in js:
        prof.remove(c)
    js.sort(key=lambda c: int(c.get("instance") or 0))
    for k, c in enumerate(js):
        prof.insert(first + k, c)
