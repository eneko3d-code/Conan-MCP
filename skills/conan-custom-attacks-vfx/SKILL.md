---
name: conan-custom-attacks-vfx
description: Make custom attacks and abilities for Conan Exiles playable with ConanMCP — study a vanilla attack, reuse its gameplay notifies (damage windows, traces, sounds), add Niagara/Cascade particles and trails at sockets, build the montage and hook it to a weapon, item or NPC. Use after authoring an animation or when the user wants VFX on an existing one.
---

# Custom attacks and abilities with particles

## 1. Study a vanilla reference first
- `find_animations` (`kind: montage`, query like `Attack`, `Combo`, `Sword`, `Axe`, `Heavy`, `Cast`, or the
  creature name) and pick the closest vanilla move.
- `get_animation_info` on it: length, slot, sections and **every notify** with class, time and properties.
  Note the impact time and the gameplay notifies (damage windows, weapon traces, stamina, sounds, camera shake).
  Those classes are what make an attack deal damage in Conan; never invent them.
- Match your animation's timing to it when possible (same total length, impact at a similar time): then the
  vanilla windows line up without re-timing.

## 2. Make it playable
Two ways, prefer the first:
1. `create_montage` with `template_montage` = the vanilla montage: duplicates it into your mod, keeps its
   notifies and sections, and swaps in your animation. Read the `note` about duration mismatch.
2. `create_montage` from your AnimSequence, then `copy_animation_notifies` from the vanilla montage/sequence
   (`time_mode: scale` re-times everything to your length; `include_classes`/`exclude_classes` to filter;
   `dry_run` first). Check `properties_failed` in the report.
Then `get_animation_info` on the result and verify each window sits around your impact frame.

## 3. Particles, trails and sound
- Find effects: `find_particle_systems` / `find_conan_particles` (fire, blood, sparks, magic, dust...).
  To change one, `duplicate_asset` it into `/Game/Mods/<Mod>/VFX/` first; never edit base effects.
- Sockets: `get_skeleton_sockets` / `get_character_sockets` (weapon, hand, foot, head). Use the weapon socket
  for weapon effects and hands or feet for body effects.
- `add_animation_notify`:
  - burst on impact: `kind: niagara` (or `cascade`) at the impact time, `properties: {system, socket, location_offset, scale}`;
  - trail during the swing: `kind: trail` (Cascade, with `socket` and `second_socket` along the blade) or
    `niagara_timed` from anticipation end to impact end;
  - charge-up for abilities: `niagara_timed` on the hand during anticipation, then a burst on release;
  - sound: `kind: sound` with `properties: {sound}` slightly before impact (2 frames) for punch.
- `preview_ability` on your preview character: it shows the move, spawns its particles at their sockets and
  returns frame captures. Clean up afterwards with `remove_preview_particle`.

## 4. Hook it into the game
Conan picks attacks and abilities from DataTables and Blueprints that vary by version, so **discover, don't assume**:
- `find_conan_datatables` (queries like `Combo`, `Attack`, `Weapon`, `Ability`, `Montage`, `NPC`) and
  `search_datatable_rows` for the vanilla montage's path to find where it is referenced.
- `get_datatable_schema` on that table, then `duplicate_datatable_row` into your mod table, pointing it at your
  montage (`update_datatable_row`). For NPC/creature attacks, look for their attack/behaviour tables the same way.
- If a Blueprint references it instead, `get_blueprint_info` and change the default with `set_blueprint_default`
  on a subclass in your mod.

## 5. Validate
`audit_mod`, `validate_assets`, `save_all_dirty`, then test in PIE: damage on hit, VFX at the right socket and
time, no foot sliding, transitions back to idle. Report timings (impact s), assets created and what the user
should test.

## Honest limits
- New Niagara systems cannot be built from scratch through the API: duplicate and adjust existing ones
  (exposed user parameters, scale, offsets) or ask the user to tweak them in the Niagara editor.
- Damage values and combo logic live in Conan's own data. Copy vanilla patterns and change values in your
  mod's rows; do not edit base-game tables.
