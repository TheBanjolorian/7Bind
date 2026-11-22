from conftest import fixture_bytes

from sevenbind import actionmaps, remap


def live():
    return actionmaps.parse(fixture_bytes("live_actionmaps.xml"))


def test_counts_match_costas_live_setup():
    p = live()
    assert len(p.active) == 60
    assert len(p.removed) == 22
    names = [d.name for d in p.joysticks]
    assert names == ["VPC Panel #1", "LEFT VPC Stick WarBRD", "vJoy Device", "RIGHT VPC Stick WarBRD", "VPC MongoosT-50CM3"]
    s = actionmaps.summary(p)
    per = {d["key"]: d["bindings"] for d in s["devices"] if d["kind"] == "joystick"}
    assert per == {"js1": 14, "js2": 12, "js3": 2, "js4": 24, "js5": 8}
    assert s["curves"] == 2
    left = p.device("joystick", 2)
    assert left.guid == "80CC3344-0000-0000-0000-504944564944"
    assert left.inverted == ["flight_strafe_longitudinal"]


def test_conflicts_found():
    c = {x["input"]: x["actions"] for x in actionmaps.conflicts(live())}
    assert c["js1_button11"] == ["v_autoland", "v_toggle_all_doorlocks"]
    assert c["js2_button6"] == ["v_master_mode_cycle", "v_toggle_qdrive_engagement"]
    assert set(c["js4_button4"]) == {"v_scanning_trigger_scan", "v_weapon_preset_fire_guns0", "v_weapon_toggle_launch_missile"}


def test_labels():
    p = live()
    b = next(b for b in p.bindings if b.input == "js1_button7")
    assert actionmaps.input_label(b) == "Button 7"
    assert actionmaps.action_label(b.action) == "Flight ready"
    ax = next(b for b in p.bindings if b.input == "js4_y")
    assert actionmaps.input_label(ax) == "Y axis"
    assert actionmaps.action_label("v_some_new_thing") == "Some new thing"


def test_press_types():
    b = actionmaps.Binding("m", "a", "kb1_n", "keyboard", 1, "n", False, activation="delayed_hold")
    assert b.press == "hold"
    b2 = actionmaps.Binding("m", "a", "kb1_n", "keyboard", 1, "n", False, multitap=2)
    assert b2.press == "double_tap"
    b3 = actionmaps.Binding("m", "a", "kb1_lalt+n", "keyboard", 1, "lalt+n", False)
    assert b3.press == "modifier"


def test_same_button_different_press_is_not_a_conflict():
    xml = b"""<ActionMaps><ActionProfiles><actionmap name="spaceship_general">
    <action name="v_autoland"><rebind input="js1_button11" activationMode="delayed_hold"/></action>
    <action name="v_toggle_all_doorlocks"><rebind input="js1_button11"/></action>
    </actionmap></ActionProfiles></ActionMaps>"""
    assert actionmaps.conflicts(actionmaps.parse(xml)) == []


def test_match_and_remap_after_renumbering():
    src = live()
    # On the new PC: right stick got js2, left js3, mongoose js4, no vJoy.
    new_pc = actionmaps.parse(b"""<ActionMaps><ActionProfiles>
      <options type="joystick" instance="1" Product="VPC Panel #1  {02593344-0000-0000-0000-504944564944}"/>
      <options type="joystick" instance="2" Product="RIGHT VPC Stick WarBRD  {40CC3344-0000-0000-0000-504944564944}"/>
      <options type="joystick" instance="3" Product="LEFT VPC Stick WarBRD  {80CC3344-0000-0000-0000-504944564944}"/>
      <options type="joystick" instance="4" Product="VPC MongoosT-50CM3  {01943344-0000-0000-0000-504944564944}"/>
    </ActionProfiles></ActionMaps>""")
    matches = remap.match_devices(src, new_pc.devices)
    m = remap.mapping_from(matches)
    assert m == {1: 1, 2: 3, 3: None, 4: 2, 5: 4}
    out, stats = remap.apply(fixture_bytes("live_actionmaps.xml"), m, new_pc.devices)
    p = actionmaps.parse(out)
    assert stats["skipped"] == 2          # the vJoy bindings
    pitch = next(b for b in p.bindings if b.action == "v_pitch")
    assert pitch.input == "js2_y"         # right stick moved from js4 to js2
    lat = next(b for b in p.bindings if b.action == "v_strafe_lateral")
    assert lat.input == "js3_x"           # left stick moved from js2 to js3
    assert not any(b.input.startswith("js3_") and b.action in ("v_strafe_forward", "v_strafe_back") for b in p.bindings)
    left = p.device("joystick", 3)
    assert left.name == "LEFT VPC Stick WarBRD" and "flight_strafe_longitudinal" in left.curves
    inst = [d.instance for d in p.devices if d.kind == "joystick"]
    assert inst == sorted(inst) and len(inst) == len(set(inst)) == 8
    assert len(p.active) == 58
