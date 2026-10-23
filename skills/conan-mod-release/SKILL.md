---
name: conan-mod-release
description: Prepare a Conan Exiles mod for testing and release with ConanMCP (folder layout, audit, broken references, cross-mod dependencies, naming, saving). Use before testing, cooking, uploading or when the user asks if a mod is ready.
---

# Mod structure and release checklist

## New mod
`create_mod_structure` with `mod_name` creates `/Game/Mods/<Mod>/{Blueprints, DataTables, Items, Icons, Maps,
Meshes, Materials, Textures, VFX, Audio, UI}`. The mod still has to be registered with the DevKit's own mod tools.
Keep **every** new asset inside the mod folder.

## Before every test or release
1. `audit_mod`: score, checks and a to-do list.
2. `validate_assets` on the mod folder: fix each missing dependency (re-point the reference, or restore the asset).
3. Cross-mod dependencies: the mod would require the other mod to load. Remove them unless intended and documented.
4. Naming: fix prefixes when cheap (`rename_asset` keeps references and fixes redirectors).
5. `list_dirty_packages` → `save_all_dirty`.
6. `get_output_log` with `min_level: error` after loading the map: there should be no new errors from the mod.
7. Test in PIE and on a local dedicated server, then cook and upload with the DevKit's mod tools.

## Deleting assets
`delete_asset` is DESTRUCTIVE (disabled by default), refuses referenced assets and cannot be undone with Ctrl+Z.
Prefer moving unused assets into an `_Unused` folder with `rename_asset`.

## Report to the user
List the score, every failed check with the concrete assets involved, what you fixed, and what still needs a
human decision.
