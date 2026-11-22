"""Reads Star Citizen's actionmaps.xml: devices, bindings, removals, curves, press types.

The file holds only what the player changed. An empty input ("js1_ ", "kb1_ ")
means the player removed a default binding. Devices are listed as
<options type="joystick" instance="N" Product="NAME  {GUID}">; bindings refer to
them by prefix and instance: js4_button7, kb1_n, mo1_mouse1, gp1_a.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

PREFIX_KIND = {"js": "joystick", "kb": "keyboard", "mo": "mouse", "gp": "gamepad"}
KIND_PREFIX = {v: k for k, v in PREFIX_KIND.items()}
_INPUT_RE = re.compile(r"^(js|kb|mo|gp)(\d+)_(.*)$", re.IGNORECASE)
_PRODUCT_RE = re.compile(r"^(.*?)\s*\{([0-9A-Fa-f-]{8,})\}\s*$")


@dataclass
class Device:
    kind: str                  # joystick | keyboard | mouse | gamepad
    instance: int
    product: str = ""          # as in the file, e.g. "VPC Panel #1  {02593344-...}"
    name: str = ""             # "VPC Panel #1"
    guid: str | None = None    # "02593344-0000-0000-0000-504944564944"
    curves: list[str] = field(default_factory=list)     # actions with a custom curve
    inverted: list[str] = field(default_factory=list)   # actions set to invert

    @property
    def key(self) -> str:
        return f"{KIND_PREFIX.get(self.kind, '?')}{self.instance}"

    def as_dict(self) -> dict:
        return {"kind": self.kind, "instance": self.instance, "name": self.name, "guid": self.guid,
                "key": self.key, "curves": self.curves, "inverted": self.inverted}


@dataclass
class Binding:
    actionmap: str
    action: str
    input: str                 # raw, e.g. "js4_button7"
    kind: str | None           # joystick | keyboard | mouse | gamepad | None (unparsable)
    instance: int | None
    key: str                   # part after the prefix, e.g. "button7", "lalt+n"; "" when removed
    removed: bool
    activation: str | None = None   # activationMode attribute, if any
    multitap: int | None = None     # multiTap attribute, if any

    @property
    def device_key(self) -> str | None:
        return f"{KIND_PREFIX[self.kind]}{self.instance}" if self.kind and self.instance is not None else None

    @property
    def press(self) -> str:
        a = (self.activation or "").lower()
        if self.multitap and self.multitap >= 2 or "double" in a:
            return "double_tap"
        if "hold" in a or "long" in a or "delayed" in a:
            return "hold"
        if "+" in self.key:
            return "modifier"
        return "tap"


@dataclass
class Profile:
    devices: list[Device]
    bindings: list[Binding]

    def device(self, kind: str, instance: int) -> Device | None:
        return next((d for d in self.devices if d.kind == kind and d.instance == instance), None)

    @property
    def joysticks(self) -> list[Device]:
        return [d for d in self.devices if d.kind == "joystick" and d.product]

    @property
    def active(self) -> list[Binding]:
        return [b for b in self.bindings if not b.removed]

    @property
    def removed(self) -> list[Binding]:
        return [b for b in self.bindings if b.removed]


def split_product(product: str) -> tuple[str, str | None]:
    m = _PRODUCT_RE.match(product or "")
    if m:
        return m.group(1).strip(), m.group(2).upper()
    return (product or "").strip(), None


def parse_input(raw: str) -> tuple[str | None, int | None, str]:
    m = _INPUT_RE.match(raw or "")
    if not m:
        return None, None, (raw or "").strip()
    return PREFIX_KIND[m.group(1).lower()], int(m.group(2)), m.group(3).strip()


def parse(data: bytes | str) -> Profile:
    root = ET.fromstring(data)
    prof = root.find("ActionProfiles") if root.tag != "ActionProfiles" else root
    if prof is None:
        prof = root
    devices: list[Device] = []
    for opt in prof.findall("options"):
        kind = (opt.get("type") or "").lower()
        try:
            inst = int(opt.get("instance") or "0")
        except ValueError:
            continue
        product = opt.get("Product") or ""
        name, guid = split_product(product)
        d = Device(kind, inst, product, name, guid)
        for child in opt:
            if child.find("nonlinearity_curve") is not None or child.find("exponent") is not None:
                d.curves.append(child.tag)
            if child.get("invert") == "1":
                d.inverted.append(child.tag)
        devices.append(d)
    bindings: list[Binding] = []
    for am in prof.findall("actionmap"):
        amname = am.get("name") or ""
        for action in am.findall("action"):
            aname = action.get("name") or ""
            for rb in action.findall("rebind"):
                raw = rb.get("input") or ""
                kind, inst, key = parse_input(raw)
                mt = rb.get("multiTap")
                bindings.append(Binding(amname, aname, raw, kind, inst, key, removed=(key == ""),
                                        activation=rb.get("activationMode"),
                                        multitap=int(mt) if mt and mt.isdigit() else None))
    return Profile(devices, bindings)


# ------------------------------------------------------------------ labels

CATEGORY = {
    "spaceship_movement": "Flight", "spaceship_general": "Ship", "seat_general": "Flight",
    "spaceship_view": "View", "spaceship_quantum": "Quantum", "spaceship_targeting": "Targeting",
    "spaceship_targeting_advanced": "Targeting", "spaceship_radar": "Scanning", "spaceship_scanning": "Scanning",
    "spaceship_weapons": "Weapons", "spaceship_missiles": "Missiles", "spaceship_defensive": "Defense",
    "spaceship_power": "Power", "lights_controller": "Ship", "vehicle_general": "View", "vehicle_mfd": "Ship",
    "player_input_optical_tracking": "View", "player": "On foot", "mining": "Mining", "salvage": "Salvage",
}
CATEGORY_ORDER = ["Flight", "Ship", "Weapons", "Missiles", "Defense", "Targeting", "Power", "Quantum",
                  "Scanning", "View", "On foot", "Mining", "Salvage", "Other"]

ACTION_LABELS = {
    "v_flightready": "Flight ready", "v_toggle_all_doorlocks": "Lock/unlock all doors",
    "v_toggle_all_doors": "Open/close all doors", "v_accel_range_abs": "Acceleration limiter",
    "v_afterburner": "Afterburner", "v_atc_request": "Request landing (ATC)", "v_autoland": "Autoland",
    "v_ifcs_speed_limiter_abs": "Speed limiter", "v_ifcs_speed_limiter_toggle": "Speed limiter on/off",
    "v_ifcs_throttle_swap_mode": "Throttle swap mode", "v_ifcs_toggle_esp": "ESP on/off",
    "v_ifcs_toggle_gforce_safety": "G-force safety on/off", "v_ifcs_vector_decoupling_toggle": "Decoupled mode",
    "v_master_mode_cycle": "Master mode cycle", "v_pitch": "Pitch", "v_roll": "Roll", "v_yaw": "Yaw",
    "v_space_brake": "Space brake", "v_strafe_back": "Strafe back", "v_strafe_forward": "Strafe forward",
    "v_strafe_down": "Strafe down", "v_strafe_up": "Strafe up", "v_strafe_left": "Strafe left",
    "v_strafe_right": "Strafe right", "v_strafe_lateral": "Strafe left/right",
    "v_strafe_longitudinal": "Strafe forward/back", "v_strafe_vertical": "Strafe up/down",
    "v_strafe_longitudinal_invert": "Invert strafe forward/back", "v_strafe_trim_reset_long": "Strafe trim reset (hold)",
    "v_strafe_trim_reset_short": "Strafe trim reset", "v_toggle_landing_system": "Landing gear",
    "v_transform_cycle": "Transform cycle", "v_vtol_toggle": "VTOL", "v_toggle_qdrive_engagement": "Quantum drive engage",
    "v_target_unlock": "Unlock target", "v_target_cycle_all_fwd": "Cycle all targets",
    "v_target_cycle_attacker_fwd": "Cycle attackers", "v_target_cycle_attacker_reset": "Reset attacker cycle",
    "v_target_cycle_subitem_back": "Previous sub-target", "v_target_cycle_subitem_fwd": "Next sub-target",
    "v_target_cycle_subitem_reset": "Reset sub-target", "v_target_under_reticle": "Target under reticle",
    "v_invoke_ping": "Radar ping", "v_scanning_trigger_scan": "Scan", "v_weapon_pip_fade_on": "PIP fade",
    "v_weapon_pip_toggle_lead_lag": "PIP lead/lag", "v_weapon_preset_attack": "Weapon preset attack",
    "v_weapon_preset_fire_guns0": "Fire gun group 1", "v_weapon_preset_fire_guns1": "Fire gun group 2",
    "v_weapon_preset_next": "Next weapon preset", "v_weapon_preset_prev": "Previous weapon preset",
    "v_weapon_preset_qid": "Quantum interdiction", "v_weapon_preset_qid_jammer": "Quantum jammer",
    "v_weapon_cycle_missile_back": "Previous missile type", "v_weapon_cycle_missile_fwd": "Next missile type",
    "v_weapon_decrease_max_missiles": "Missiles −", "v_weapon_increase_max_missiles": "Missiles +",
    "v_weapon_reset_max_missiles": "Reset missile count", "v_weapon_toggle_launch_missile": "Launch missile",
    "v_weapon_countermeasure_decoy_burst_decrease": "Decoy burst −",
    "v_weapon_countermeasure_decoy_burst_increase": "Decoy burst +",
    "v_weapon_countermeasure_decoy_launch": "Launch decoy", "v_weapon_countermeasure_decoy_launch_panic": "Panic decoy",
    "v_weapon_countermeasure_noise_launch": "Launch noise",
    "v_engineering_assignment_engine_decrease": "Engines power −", "v_engineering_assignment_engine_increase": "Engines power +",
    "v_engineering_assignment_shields_decrease": "Shields power −", "v_engineering_assignment_shields_increase": "Shields power +",
    "v_engineering_assignment_weapons_decrease": "Weapons power −", "v_engineering_assignment_weapons_increase": "Weapons power +",
    "v_lights": "Lights", "v_view_pitch": "Look up/down", "v_view_yaw": "Look left/right",
    "v_view_yaw_right": "Look right", "v_mfd_interact_cycle_forwards_long": "MFD cycle (hold)",
    "v_operator_mode_cycle_forward": "Operator mode cycle", "headtrack_recenter_device": "Recenter head tracking",
}


def action_label(action: str) -> str:
    if action in ACTION_LABELS:
        return ACTION_LABELS[action]
    s = re.sub(r"^(v_|pc_|ui_)", "", action).replace("_", " ").strip()
    return s[:1].upper() + s[1:] if s else action


def category(actionmap: str) -> str:
    return CATEGORY.get(actionmap, "Other")


_KEY_NAMES = {"lalt": "L-Alt", "ralt": "R-Alt", "lctrl": "L-Ctrl", "rctrl": "R-Ctrl", "lshift": "L-Shift",
              "rshift": "R-Shift", "space": "Space", "tab": "Tab", "escape": "Esc", "enter": "Enter",
              "backspace": "Backspace", "capslock": "Caps Lock", "mouse1": "Left button", "mouse2": "Right button",
              "mouse3": "Middle button", "mwheel_up": "Wheel up", "mwheel_down": "Wheel down",
              "maxis_x": "Move X", "maxis_y": "Move Y"}


def input_label(b: Binding) -> str:
    if b.removed:
        return "—"
    parts = []
    for k in b.key.split("+"):
        k = k.strip()
        if b.kind in ("joystick", "gamepad"):
            m = re.match(r"^button(\d+)$", k)
            if m:
                parts.append(f"Button {m.group(1)}"); continue
            m = re.match(r"^slider(\d+)$", k)
            if m:
                parts.append(f"Slider {m.group(1)}"); continue
            m = re.match(r"^rot([xyz])$", k)
            if m:
                parts.append(f"{m.group(1).upper()} rotation"); continue
            m = re.match(r"^hat(\d+)_(\w+)$", k)
            if m:
                parts.append(f"Hat {m.group(1)} {m.group(2)}"); continue
            if k in ("x", "y", "z"):
                parts.append(f"{k.upper()} axis"); continue
        if k in _KEY_NAMES:
            parts.append(_KEY_NAMES[k]); continue
        m = re.match(r"^f(\d+)$", k)
        parts.append(k.upper() if (len(k) <= 3 or m) else k.replace("_", " ").title())
    return " + ".join(parts)


# ------------------------------------------------------------------ analysis

def conflicts(p: Profile) -> list[dict]:
    """Two or more actions on exactly the same input and press type."""
    by: dict[tuple, list[Binding]] = {}
    for b in p.active:
        by.setdefault((b.input.lower(), b.press), []).append(b)
    out = []
    for (inp, press), bs in by.items():
        actions = sorted({b.action for b in bs})
        if len(actions) > 1:
            out.append({"input": bs[0].input, "press": press, "actions": actions,
                        "labels": [action_label(a) for a in actions], "device": bs[0].device_key})
    return sorted(out, key=lambda c: c["input"])


def summary(p: Profile) -> dict:
    per: dict[str, int] = {}
    for b in p.active:
        if b.device_key:
            per[b.device_key] = per.get(b.device_key, 0) + 1
    devs = []
    for d in p.devices:
        if d.kind == "joystick" and not d.product:
            continue
        devs.append({**d.as_dict(), "bindings": per.get(d.key, 0)})
    return {
        "bindings": len(p.active),
        "removed": len(p.removed),
        "curves": sum(len(d.curves) for d in p.devices),
        "devices": devs,
        "conflicts": conflicts(p),
    }


def _norm(name: str) -> str:
    """Curve/invert options use names like flight_move_strafe_lateral for the action v_strafe_lateral."""
    return re.sub(r"^(v_|flight_move_|flight_|vehicle_)", "", name or "")


def rows(p: Profile) -> list[dict]:
    """Flat, readable rows for the bindings sheet and CSV."""
    out = []
    for b in p.bindings:
        dev = p.device(b.kind, b.instance) if b.kind and b.instance is not None else None
        dname = dev.name if dev and dev.name else {"keyboard": "Keyboard", "mouse": "Mouse", "gamepad": "Gamepad"}.get(b.kind or "", "Other")
        notes = []
        a = _norm(b.action)
        if dev and any(_norm(t) == a for t in dev.curves):
            notes.append("curve")
        if dev and any(_norm(t) == a for t in dev.inverted):
            notes.append("inverted")
        out.append({
            "device": dname, "device_key": b.device_key or "", "kind": b.kind or "",
            "input": b.input, "input_label": input_label(b), "press": b.press,
            "action": b.action, "action_label": action_label(b.action),
            "actionmap": b.actionmap, "category": category(b.actionmap),
            "source": "removed" if b.removed else "mine", "notes": notes,
        })
    return out


def diff(old: Profile | None, new: Profile) -> dict:
    """What changed in bindings between two profiles (for 'What changed')."""
    def keyset(p: Profile | None) -> set[tuple]:
        return {(b.actionmap, b.action, b.input) for b in p.bindings} if p else set()
    a, b = keyset(old), keyset(new)
    changed_actions = {(x[0], x[1]) for x in a ^ b}
    return {"bindings_changed": len(changed_actions)}
