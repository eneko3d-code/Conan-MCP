# Animations, custom attacks and abilities

ConanMCP lets an AI agent build animations with **Control Rig** from a reference you give it (an image, several
images, a sketch or just a description), then turn them into playable attacks or abilities with particles.

The agent sees your image in its own context (Claude, Antigravity, Cursor...). The server gives it the tools to
pose the character, look at the result and iterate. Two skills drive the process:
`conan-animation-from-reference` and `conan-custom-attacks-vfx`.

## Requirements

- The DevKit's **Control Rig** and **Sequencer** (enabled in standard UE5 editors). Check
  `get_server_capabilities`: `control_rig_sequencer`, `fk_control_rig`, `level_sequence`, `export_anim_sequence`.
- Without Control Rig everything still works: keys are kept in a spec and baked straight into the
  AnimSequence (`bake_animation` reports `backend: direct_bone_tracks`).
- Assets are always created inside `/Game/Mods/<YourMod>/Animations/`.

## How posing works

- **Roles instead of bone names.** `get_skeleton_roles` maps any skeleton (Unreal, 3ds Max Biped, Mixamo,
  creatures with tails, wings or four legs) to roles like `pelvis`, `spine_2`, `upperarm_r`, `forearm_r`,
  `thigh_l`, `tail_3`, `front_foot_l` or `jaw`.
- **Additive degrees.** `set_pose_keys` takes rotations relative to the rest pose (`pitch`/`yaw`/`roll` in
  degrees) and composes them with the reference pose before writing the FK Control Rig control
  (`<bone>_CONTROL`). With `mode: absolute` you set local rotations directly. With a custom rig (`rig_path`)
  you key its controls by name.
- **Joint limits.** Elbows, knees, spine, neck and the rest are clamped to sane ranges, and the result lists
  what was clamped.
- **Calibration.** Bone axes differ between skeletons. The skill tells the agent to key three test rotations
  and look at them first.
- **Timing templates.** `generate_attack_keys` turns 2–4 key poses into a full timeline
  (`light_attack`, `heavy_attack`, `thrust`, `spin_attack`, `cast`, `slam`), with an overshoot after impact and
  a settle during recovery, and returns the impact frame.
- **Visual loop.** `capture_animation_frames` returns images of chosen frames from `front`, `side`,
  `three_quarter`, `back` or `top`, so the agent can compare them with your reference.

Every animation keeps a spec in `Saved/ConanMCP/animations/<name>.json` (bones, roles, reference pose, keys).

## Example: "overhead slash with a fire trail and an explosion on impact"

What you type, with a reference image attached:

> Make this attack for the human male (`/Game/Characters/humans/meshes/SK_human_male`), mod `FireBlade`.
> Heavy overhead slash, fire trail on the sword and an explosion when it hits.

What the agent does (summarised):

1. `get_server_capabilities`, then `get_skeleton_roles mesh_path=.../SK_human_male`.
2. `create_animation_preview name=fire_slash mesh_path=... mod_name=FireBlade duration=1.4`.
3. Calibration: three `set_pose_keys` test rotations on `upperarm_r`, then `capture_animation_frames frames=[10,20,30] view=front`.
4. It reads the image: anticipation with both arms above and behind the head, torso arched back, weight on the
   back foot; impact with the arms extended forward and down, torso folded, weight on the front foot.
5. Timeline from the key poses:
   ```json
   {"name": "fire_slash", "template": "heavy_attack", "duration": 1.4, "poses": {
     "anticipation": {"spine_2": {"rotation": {"pitch": -20}}, "upperarm_r": {"rotation": {"pitch": -150}},
                      "upperarm_l": {"rotation": {"pitch": -140}}, "forearm_r": {"rotation": {"pitch": -40}}},
     "impact": {"spine_2": {"rotation": {"pitch": 35}}, "upperarm_r": {"rotation": {"pitch": 40}},
                "upperarm_l": {"rotation": {"pitch": 35}}, "pelvis": {"rotation": {"pitch": 10}}}}}
   ```
   `generate_attack_keys` answers with the impact frame (for example 17, about 0.57 s).
6. `capture_animation_frames view=side`, a comparison with the reference, small corrections with `set_pose_keys`.
7. `bake_animation name=fire_slash mod_name=FireBlade` creates `/Game/Mods/FireBlade/Animations/A_fire_slash`.
8. `find_animations query=Heavy kind=montage`, then `get_animation_info` on a vanilla two-handed heavy attack.
9. `create_montage anim_path=.../A_fire_slash mod_name=FireBlade template_montage=<vanilla montage>` keeps
   Conan's damage windows and swaps in the new animation (or `copy_animation_notifies time_mode=scale`).
10. VFX:
    - `duplicate_asset` of a vanilla fire effect into `/Game/Mods/FireBlade/VFX/`;
    - `add_animation_notify kind=trail` from the end of the anticipation to the impact (`socket` and
      `second_socket` along the blade);
    - `add_animation_notify kind=niagara time=0.57 properties={system, socket: "weapon_r"}`;
    - `kind=sound` two frames before the impact.
11. `preview_ability name=fire_slash anim_path=<montage>` shows the move with its particles and returns captures.
12. It hooks the montage into the weapon's data: `find_conan_datatables`, then `search_datatable_rows` for the
    vanilla montage path, then `duplicate_datatable_row` into the mod table.
13. Finally `audit_mod mod_name=FireBlade` and `save_all_dirty`, plus a list of what to test in PIE.

## Limits

- The server does not process images. The agent's model interprets them, so better and clearer references
  (side view, a frame per key pose) give better results.
- New Niagara systems cannot be created from scratch through Python. Duplicate and adjust existing ones.
- Conan's damage, combo and ability data differs between versions. The skills make the agent copy vanilla
  patterns and discover the tables instead of assuming them.
- The tools were tested against a simulated editor (`tests/test_animation.py`). Validate them in your DevKit with
  the steps above. If an engine API differs, the tool returns a clear message naming the missing function.
