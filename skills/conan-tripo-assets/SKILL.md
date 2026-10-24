---
name: conan-tripo-assets
description: Create, texture, optimise, rig and animate 3D assets with Tripo AI from the Conan Exiles DevKit through ConanMCP, spending credits only with the user's approval, then import them into the mod and place them. Use when the user asks to generate a model, prop, weapon, creature or texture with Tripo/AI.
---

# Tripo AI assets

Tripo tasks **cost the user's credits**. Never spend without explicit approval in this conversation.

## 1. Check first
1. `get_server_capabilities` → `tripo.api_key_configured`. If false, tell the user to set `TRIPO_API_KEY`
   (docs/tripo.md) and stop.
2. `tripo_get_balance`: balance, frozen credits, credits spent this session, remaining session budget.
   No balance → stop and say so. Do not try other tools to get around it.

## 2. Plan, then ask
- Call the generation tool **without** `confirm_spend`. You get a plan (parameters, balance, observed cost of
  that task type, budget left) and nothing is spent.
- Show the user what you will generate, the key options and the balance. Ask for approval.
- Only after a clear "yes": call again with `confirm_spend: true`. One approval covers the task you described,
  not a chain of new ones; ask again for texturing, retopology or rigging steps you did not mention.
- After `2010` (insufficient credits) or a budget error: stop, report, never retry.

## 3. Good prompts for Conan's world
- Describe shape, material, wear and scale: "heavy two-handed bronze war axe, leather-wrapped haft, notched
  blade, Hyborian age, realistic, game asset".
- Style words that fit Conan: barbaric, Hyborian, Stygian, Cimmerian, weathered stone, hammered iron,
  bronze, hide and leather, bone, sandstone, gold inlay.
- `negative_prompt`: "cartoon, low quality, modern, plastic, text, logo".
- Using a reference from the editor: `capture_viewport` / `capture_map_overview` produce PNGs in
  `Saved/ConanMCP/captures`. Pass the file name to `tripo_image_to_model` or as `reference_image` of
  `tripo_texture_model`. The user can also drop images in `Saved/ConanMCP/tripo/inputs`.
- No image yet? `tripo_text_to_image` (template `asset_extraction` for props, `t_pose` for characters),
  then image-to-model with the result's task_id.

## 4. Polygon budgets (pass `face_limit`, or retopologise after)
| Asset | Triangles |
|---|---|
| Small prop or item (cup, dagger, food) | 1–5k |
| Weapon or shield | 5–15k |
| Furniture, placeable | 5–20k |
| Building piece | 10–40k |
| Creature or NPC (rigged) | 20–60k |
Use `smart_low_poly` for stylised low-poly props, and `tripo_retopology` (`face_limit`, `model: v3.0`,
`smart_uv`) to fix heavy meshes.

## 5. Pipeline
1. Generate → `tripo_get_task task_id wait_seconds=20` until `success`. Look at `preview_image_url` and
   describe it to the user before more spending.
2. Optional steps, each its own approved spend, chaining `input = previous task_id`:
   - `tripo_texture_model` (`texture_text`, `reference_image`, `pbr`, `texture_quality`);
   - `tripo_retopology`;
   - creatures/NPCs: `tripo_rig_check` → `tripo_rig` (`spec: unreal`, `rig_type` from rig_check) →
     `tripo_retarget` (`preset:idle`, `preset:walk`, `preset:slash`...).
3. `tripo_import_result task_id mod_name asset_name` imports into `/Game/Mods/<Mod>/Tripo/<asset>/`.
   Static meshes as `SM_*`, rigged results as skeletal `SK_*`. If the GLB import fails, `tripo_convert` to FBX
   (another spend) and import that.
4. Place and check: `spawn_actor asset_path=<imported> snap_to_ground=true` → `focus_viewport` →
   `capture_viewport`. Check scale against a vanilla prop (Tripo uses metres with `auto_size`).
   Fix it with `import_scale` or `set_actor_transform` scale.
5. Make it game-ready: collision and LODs in the mesh editor (tell the user), material instances in the mod,
   item rows with the **conan-items-recipes** skill, animations with **conan-custom-attacks-vfx**.
6. `audit_mod`, then `save_all_dirty` when the user agrees.

## 6. Report
Task ids, credits used (`tripo_list_tasks` / `tripo_get_balance`), imported asset paths, and what still needs a
human (collision, LODs, licensing). The user is responsible for Tripo's terms of service and for Funcom's modding
EULA for generated content.
