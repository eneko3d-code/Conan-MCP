"""Animation pipeline tests: pure pose/timing/role math plus the full tool flow on the fake engine."""

import json
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "Content", "Python"))
sys.path.insert(0, HERE)

import fake_unreal as fu  # noqa: E402
import conan_mcp_server  # noqa: E402,F401
from conan_mcp.animation import pose, timing  # noqa: E402
from conan_mcp.animation.roles import map_roles, resolve  # noqa: E402
from conan_mcp.core import config, ue  # noqa: E402
from conan_mcp.core.protocol import call_tool  # noqa: E402

UE_BONES = ["root", "pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "head", "clavicle_l", "upperarm_l",
            "lowerarm_l", "hand_l", "clavicle_r", "upperarm_r", "lowerarm_r", "hand_r", "thigh_l", "calf_l", "foot_l",
            "thigh_r", "calf_r", "foot_r", "weapon_r"]


# --- pure helpers -------------------------------------------------------------

@pytest.mark.parametrize("bones,expected", [
    (UE_BONES, {"upperarm_r": "upperarm_r", "forearm_l": "lowerarm_l", "spine_3": "spine_03", "neck": "neck_01"}),
    (["Bip01", "Bip01 Pelvis", "Bip01 Spine", "Bip01 Spine1", "Bip01 R UpperArm", "Bip01 R Forearm", "Bip01 L Thigh"],
     {"pelvis": "Bip01 Pelvis", "spine_2": "Bip01 Spine1", "upperarm_r": "Bip01 R UpperArm", "forearm_r": "Bip01 R Forearm"}),
    (["mixamorig:Hips", "mixamorig:LeftArm", "mixamorig:LeftForeArm", "mixamorig:RightUpLeg", "mixamorig:RightLeg"],
     {"pelvis": "mixamorig:Hips", "upperarm_l": "mixamorig:LeftArm", "forearm_l": "mixamorig:LeftForeArm",
      "thigh_r": "mixamorig:RightUpLeg", "calf_r": "mixamorig:RightLeg"}),
    (["root", "pelvis", "spine_01", "tail_01", "tail_02", "front_thigh_l", "front_paw_l", "hind_foot_r", "jaw"],
     {"tail_2": "tail_02", "front_thigh_l": "front_thigh_l", "front_foot_l": "front_paw_l", "back_foot_r": "hind_foot_r"}),
])
def test_role_mapping(bones, expected):
    roles = map_roles(bones)["roles"]
    for role, bone in expected.items():
        assert roles.get(role) == bone, (role, roles)


def test_fingers_and_twist_are_ignored():
    roles = map_roles(UE_BONES + ["index_01_l", "upperarm_twist_01_r", "ik_hand_root"])
    assert "index_01_l" in roles["unmapped_examples"] and roles["body_type"] == "biped"
    assert resolve("upperarm_r_CONTROL", {}, UE_BONES) == "upperarm_r"


def test_rotator_quat_roundtrip_and_composition():
    for r in ({"pitch": 30, "yaw": -45, "roll": 10}, {"pitch": -80, "yaw": 170, "roll": -60}):
        q = pose.rotator_to_quat(r["pitch"], r["yaw"], r["roll"])
        back = pose.quat_to_rotator(q)
        for k in r:
            assert back[k] == pytest.approx(r[k], abs=1e-6)
    ref = {"pitch": 10, "yaw": 20, "roll": 30}
    off = {"pitch": 15, "yaw": 0, "roll": -5}
    absolute = pose.compose_additive(ref, off)
    back = pose.offset_from_absolute(ref, absolute)
    for k in off:
        assert back[k] == pytest.approx(off[k], abs=1e-3)
    assert pose.compose_additive({}, off) == pytest.approx(off)


def test_joint_limits():
    r, clamped = pose.clamp_offset("forearm_r", {"pitch": 200, "yaw": -10})
    assert clamped and r["pitch"] == 150 and r["yaw"] == -10
    assert pose.role_base("front_thigh_l") == "thigh" and pose.role_base("tail_3") == "tail"


def test_sample_keys_interpolates():
    keys = [{"frame": 0, "bones": {"b": {"rotation": {"pitch": 0}}}}, {"frame": 10, "bones": {"b": {"rotation": {"pitch": 90}}}}]
    assert pose.sample_keys(keys, "b", 5)["pitch"] == pytest.approx(45, abs=0.5)
    assert pose.sample_keys(keys, "b", 20)["pitch"] == pytest.approx(90)
    assert pose.sample_keys(keys, "x", 5) is None


def test_attack_timing_template():
    ph = timing.phase_frames("light_attack", 0.8, 30)
    assert ph[0]["start_frame"] == 0 and ph[-1]["end_frame"] == 24
    assert [p["phase"] for p in ph] == ["anticipation", "strike", "impact", "follow_through", "recovery"]
    plan = timing.generate_keys({"anticipation": {"upperarm_r": {"rotation": {"pitch": -60}}},
                                 "impact": {"upperarm_r": {"rotation": {"pitch": 70}}}}, "light_attack", 0.8, 30)
    phases = [k["phase"] for k in plan["keys"]]
    assert phases[0] == "start" and "impact" in phases and "overshoot" in phases and phases[-1] == "recovery"
    impact = next(k for k in plan["keys"] if k["phase"] == "impact")
    over = next(k for k in plan["keys"] if k["phase"] == "overshoot")
    assert over["bones"]["upperarm_r"]["rotation"]["pitch"] > impact["bones"]["upperarm_r"]["rotation"]["pitch"]
    assert plan["keys"][-1]["bones"]["upperarm_r"]["rotation"]["pitch"] == 0
    with pytest.raises(ValueError):
        timing.generate_keys({"anticipation": {}}, "light_attack")


# --- tool flow on the fake engine ------------------------------------------------

@pytest.fixture()
def anim_engine(monkeypatch, tmp_path):
    eng = fu.reset(lambda x, y: 0.0)
    monkeypatch.setattr(ue, "unreal", fu)
    monkeypatch.setattr(fu, "ConanMCPEditorLibrary", None, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "ENABLE_WRITE_TOOLS", True)
    skel = fu.Skeleton("SK_Human_Skeleton", "/Game/Characters/SK_Human_Skeleton", UE_BONES,
                       ref={"upperarm_r": {"pitch": 0, "yaw": 0, "roll": -45}})
    eng.add_asset("/Game/Characters/SK_Human", fu.SkeletalMesh("SK_Human", "/Game/Characters/SK_Human", skel))
    vanilla = fu.AnimSequence("A_Vanilla_Slash", "/Game/Animations/A_Vanilla_Slash", length=1.0)
    eng.add_asset("/Game/Animations/A_Vanilla_Slash", vanilla)
    fu.AnimationLibrary.add_animation_notify_track(vanilla, "Gameplay")
    dmg = fu.AnimationLibrary.add_animation_notify_state_event(vanilla, "Gameplay", 0.4, 0.2, fu.AnimNotifyState_ConanDamageWindow)
    dmg.set_editor_property("damage_multiplier", 1.75)
    eng.add_asset("/Game/VFX/NS_Fire", fu.NiagaraSystem("NS_Fire", "/Game/VFX/NS_Fire"))
    return eng


def call(_tool, **args):
    res = call_tool(_tool, args)
    if res["isError"]:
        raise AssertionError(res["content"][0]["text"])
    return json.loads(res["content"][0]["text"])


def call_err(_tool, **args):
    res = call_tool(_tool, args)
    assert res["isError"], res
    return res["content"][0]["text"]


def test_skeleton_roles_tool(anim_engine):
    out = call("get_skeleton_roles", mesh_path="/Game/Characters/SK_Human")
    assert out["roles"]["forearm_r"] == "lowerarm_r" and out["reference_pose_known"]


def test_full_attack_pipeline(anim_engine, monkeypatch):
    prev = call("create_animation_preview", name="fire_slash", mesh_path="/Game/Characters/SK_Human",
                mod_name="MyMod", duration=0.8)
    assert prev["control_rig_track"] and prev["sequence"] == "/Game/Mods/MyMod/Animations/Sequences/LS_fire_slash"
    seq = anim_engine.assets[prev["sequence"]]

    # additive key on a role is composed with the reference pose before reaching the FK control
    out = call("set_pose_keys", name="fire_slash", keys=[{"frame": 6, "pose": {"upperarm_r": {"rotation": {"pitch": 30}}}}])
    assert out["backend"] == "control_rig" and out["control_keys_written"] == 1
    written = seq.rig.keys[("upperarm_r_CONTROL", 6)]
    expected = pose.compose_additive({"pitch": 0, "yaw": 0, "roll": -45}, {"pitch": 30})
    assert written.pitch == pytest.approx(expected["pitch"], abs=1e-3) and written.roll == pytest.approx(expected["roll"], abs=1e-3)

    clamp = call("set_pose_keys", name="fire_slash", keys=[{"frame": 8, "pose": {"forearm_r": {"rotation": {"pitch": 400}}, "nope": {}}}],
                 dry_run=True)
    assert clamp["clamped"] == ["forearm_r@8"] and clamp["unresolved_targets"] == ["nope"]

    plan = call("generate_attack_keys", name="fire_slash", template="light_attack", duration=0.8, poses={
        "anticipation": {"upperarm_r": {"rotation": {"pitch": -70}}, "spine_2": {"rotation": {"yaw": -25}}},
        "impact": {"upperarm_r": {"rotation": {"pitch": 80}}, "spine_2": {"rotation": {"yaw": 30}}}})
    assert plan["impact_frame"] == 9 and plan["frames"] == 24

    baked = call("bake_animation", name="fire_slash", mod_name="MyMod")
    assert baked["backend"] == "control_rig_sequence" and baked["impact_time_s"] == pytest.approx(0.3, abs=0.01)
    anim = anim_engine.assets[baked["anim_path"]]
    assert anim.exported_from is seq

    mont = call("create_montage", anim_path=baked["anim_path"], mod_name="MyMod", slot_name="UpperBody")
    assert mont["montage_path"].endswith("AM_fire_slash")

    copied = call("copy_animation_notifies", source_path="/Game/Animations/A_Vanilla_Slash", target_path=baked["anim_path"])
    assert copied["copied"] == 1 and copied["time_ratio"] == pytest.approx(0.8)
    ev = anim.events[0]
    assert ev.time == pytest.approx(0.32) and ev.duration == pytest.approx(0.16)
    assert ev.obj.get_editor_property("damage_multiplier") == 1.75

    vfx = call("add_animation_notify", anim_path=baked["anim_path"], kind="niagara", time=0.33,
               properties={"system": "/Game/VFX/NS_Fire", "socket": "weapon_r"})
    assert vfx["applied"] == {"template": "/Game/VFX/NS_Fire", "socket_name": "weapon_r"} and not vfx["failed"]

    info = call("get_animation_info", anim_path=baked["anim_path"])
    assert {n["class"] for n in info["notifies"]} == {"AnimNotifyState_ConanDamageWindow", "AnimNotify_PlayNiagaraEffect"}

    class Automation:
        @staticmethod
        def take_high_res_screenshot(w, h, path, *a):
            with open(path, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\nfake")

    monkeypatch.setattr(fu, "AutomationLibrary", Automation, raising=False)
    res = call_tool("capture_animation_frames", {"name": "fire_slash", "count": 3, "view": "side"})
    assert not res["isError"], res
    images = [c for c in res["content"] if c["type"] == "image"]
    assert len(images) >= 3  # includes the impact frame


def test_direct_bake_without_control_rig(anim_engine, monkeypatch):
    monkeypatch.delattr(fu, "ControlRigSequencerLibrary")
    prev = call("create_animation_preview", name="roar", mesh_path="/Game/Characters/SK_Human", mod_name="MyMod")
    assert not prev["control_rig_track"] and prev["notes"]
    call("set_pose_keys", name="roar", keys=[{"frame": 0, "pose": {"head": {"rotation": {"pitch": 0}}}},
                                             {"time": 0.5, "pose": {"head": {"rotation": {"pitch": 40}}}}])
    baked = call("bake_animation", name="roar", mod_name="MyMod")
    assert baked["backend"] == "direct_bone_tracks" and baked["bones_baked"] == 1
    tracks = anim_engine.assets[baked["anim_path"]].controller.tracks
    pos, rots, scales = tracks["head"]
    mid = rots[15].rotator()
    assert mid.pitch == pytest.approx(40, abs=0.5)


def test_animation_writes_stay_in_mods(anim_engine):
    assert "/Game/Mods" in call_err("add_animation_notify", anim_path="/Game/Animations/A_Vanilla_Slash", time=0.1)
    assert "/Game/Mods" in call_err("create_animation_preview", name="x", mesh_path="/Game/Characters/SK_Human",
                                    package_path="/Game/Characters")
    out = call("duplicate_asset", source_path="/Game/VFX/NS_Fire", destination_path="/Game/Mods/MyMod/VFX/NS_MyFire")
    assert out["duplicated"] == "/Game/Mods/MyMod/VFX/NS_MyFire"


def test_montage_from_vanilla_template(anim_engine):
    tpl = fu.AnimMontage("AM_Vanilla", "/Game/Animations/AM_Vanilla", anim_engine.assets["/Game/Animations/A_Vanilla_Slash"])
    anim_engine.add_asset("/Game/Animations/AM_Vanilla", tpl)
    mine = fu.AnimSequence("A_Mine", "/Game/Mods/MyMod/Animations/A_Mine", length=1.4)
    anim_engine.add_asset("/Game/Mods/MyMod/Animations/A_Mine", mine)
    out = call("create_montage", anim_path="/Game/Mods/MyMod/Animations/A_Mine", mod_name="MyMod",
               template_montage="/Game/Animations/AM_Vanilla")
    new = anim_engine.assets[out["montage_path"]]
    seg = new.get_editor_property("slot_anim_tracks")[0].get_editor_property("anim_track").get_editor_property("anim_segments")[0]
    assert seg.get_editor_property("anim_reference") is mine and "Re-time" in out["note"]
