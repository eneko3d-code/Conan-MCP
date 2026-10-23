---
name: conan-animation-from-reference
description: Turn a reference (image, sketch, video frames or a description) into a Conan Exiles animation with Control Rig through ConanMCP — read the pose, pick key poses, key controls, compare captures with the reference, bake. Use for any "make this animation / pose / attack / emote" request, for humans, NPCs or creatures.
---

# Animation from a reference

You are the animator. The reference image is in your context; the editor is reached only through tools.
Work **key pose first, timing second, polish last**, and always check your result against the reference visually.

## 0. Setup
1. `get_server_capabilities` — check `control_rig_sequencer`, `level_sequence`, `export_anim_sequence`,
   `reference_pose`. Without Control Rig the same tools still work: keys are baked directly.
2. Pick the mesh: `find_assets` (class `SkeletalMesh`) for the character, NPC or creature.
3. `get_skeleton_roles` — you will pose by **role** (`pelvis`, `spine_1..3`, `neck`, `head`, `clavicle_r`,
   `upperarm_r`, `forearm_r`, `hand_r`, `thigh_l`, `calf_l`, `foot_l`, `tail_1..n`, `front_thigh_l`, `jaw`...).
4. `create_animation_preview` with `mesh_path`, `name`, `mod_name`, `duration` (FK Control Rig by default;
   pass `rig_path` for a custom rig with IK — then pose its controls by name).

## 1. Calibrate axes once per skeleton (do not skip)
Bone axes differ between rigs. Key three test poses and look:
```
set_pose_keys keys=[{frame:10, pose:{upperarm_r:{rotation:{pitch:40}}}},
                    {frame:20, pose:{upperarm_r:{rotation:{yaw:40}}}},
                    {frame:30, pose:{upperarm_r:{rotation:{roll:40}}}}]
capture_animation_frames frames=[10,20,30] view=front
```
Write down which axis raises the arm forward, sideways and twists it; do the same for `spine_2` and `thigh_r`
if the pose involves them. Then `set_pose_keys` the same frames back to 0 (or recreate the preview).
Mirrored sides usually invert the sign of yaw/roll.

## 2. Read the reference
Describe it before touching the rig:
- **Action and phase**: what is happening, which moment (anticipation, impact, follow-through, rest).
- **Line of action**: the main curve through the body (C or S), lean direction, where the weight is.
- **Silhouette**: which limbs read from the camera, what is the most extreme angle.
- **Per role**, estimate rotations in degrees relative to the rest pose (shoulder raised ~90, elbow bent ~60,
  torso twisted ~30 towards the right...). Round to 5°.
- **Weapon / hand**: grip, which hand leads, where the weapon points.
For a sequence of images, treat each as a key pose and order them in time.

## 3. Pose (additive degrees on roles)
- `set_pose_keys` with `mode: additive` (default): `{frame, pose: {role: {rotation: {pitch, yaw, roll}}}}`.
- Pose from the core outwards: pelvis → spine chain (distribute twist over spine_1..3, ~1/3 each) → neck/head →
  clavicles → arms → hands → legs. Keep the head counter-rotating so the eyes stay on target.
- Joint limits are enforced (the result tells you what was clamped). Elbows and knees bend one way only.
- Use `dry_run: true` to check resolution of every role before writing.

## 4. Compare and correct (the loop that makes it right)
`capture_animation_frames` with the **same view as the reference** (`front`, `side`, `three_quarter`, `back`)
and the key frames. Compare silhouette, line of action, limb angles and weapon direction. Fix the biggest
difference first, re-key, capture again. Two or three iterations are normal; stop when a person would recognise
the reference pose.

## 5. Timing and motion
- Attacks/abilities: let `generate_attack_keys` build the timeline from your key poses
  (`poses: {start?, anticipation, impact, follow_through?}`, `template`: light_attack, heavy_attack, thrust,
  spin_attack, cast, slam). It adds overshoot and settle keys.
- Typical timing at 30 fps: light attack 0.6–0.9 s, heavy 1.2–1.8 s; anticipation ~30%, strike 2–4 frames,
  recovery ~40%. Readability beats realism: slow anticipation, very fast strike, clear hold on impact.
- Principles: arcs (hands and weapon tip travel on curves), overlap (head/hand lag 1–2 frames behind the torso),
  weight (pelvis drops on impact, knees absorb), balance (pelvis stays over the support feet), no foot sliding
  (keep planted feet un-keyed or keep the legs still unless stepping).
- Creatures: same method with their roles (tail_* follows the spine with delay, jaw opens on roars/bites,
  front/back legs push in opposition).

## 6. Bake and hand off
`bake_animation` (creates `/Game/Mods/<Mod>/Animations/A_<name>`, reports the impact time) → `create_montage`
→ continue with the **conan-custom-attacks-vfx** skill to make it playable and add particles.
Tell the user the asset paths, the key frames and what they could refine by hand in Sequencer.
