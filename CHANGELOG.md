# Changelog

## 2.2.0 — Tripo AI integration
- 15 new tools (128 in total):
  - account and tasks: `tripo_get_balance`, `tripo_get_task`, `tripo_list_tasks`, `tripo_upload_file`;
  - generation: `tripo_text_to_model`, `tripo_image_to_model`, `tripo_multiview_to_model`, `tripo_text_to_image`;
  - processing: `tripo_texture_model`, `tripo_retopology`, `tripo_convert`;
  - rigging and animation: `tripo_rig_check`, `tripo_rig`, `tripo_retarget`;
  - import: `tripo_import_result` (download plus import into `/Game/Mods/<Mod>/Tripo`).
- Spending control: balance check before every task, plan-only unless `confirm_spend=true`, session budget
  `CONAN_MCP_TRIPO_BUDGET`, minimum balance `CONAN_MCP_TRIPO_MIN_BALANCE`, real `credits_consumed` accounting,
  and no retries after error 2010.
- Security:
  - the API key is read from `TRIPO_API_KEY` and never stored or echoed;
  - downloads only from HTTPS Tripo hosts;
  - uploads only from `Saved/ConanMCP`.
- Tools can now run off the Game Thread (network work never freezes the editor). The `openWorldHint` annotation
  is set for Tripo tools.
- Skill `conan-tripo-assets` and `docs/tripo.md`. Fake Tripo v3 server tests (102 tests in total).

## 2.1.0 — Animation with Control Rig, custom attacks and abilities with particles
### New: 16 tools (113 in total)
- **Posing by role**: `get_skeleton_roles` maps Unreal, Biped, Mixamo and creature skeletons to roles
  (`upperarm_r`, `spine_2`, `tail_3`, `front_foot_l`...). Also `get_reference_pose` and `get_control_rig_controls`.
- **Authoring**:
  - `create_animation_preview`: preview character, LevelSequence and an FK or custom Control Rig track;
  - `set_pose_keys`: additive or absolute degrees, joint limits, dry run;
  - `generate_attack_keys`: attack/ability timing templates with overshoot and settle.
- **Visual loop**: `capture_animation_frames` returns multi-frame images from front, side, three-quarter, back or top views.
- **Output**:
  - `bake_animation`: from the Control Rig sequence, or directly from the keys when Control Rig is unavailable;
  - `create_montage`: new, or from a vanilla template that keeps its gameplay notifies.
- **Notifies and VFX**:
  - `add_animation_notify`: Niagara/Cascade bursts, timed effects, trails, sounds and custom classes;
  - `copy_animation_notifies`: vanilla damage windows, re-timed;
  - `remove_animation_notifies` and `duplicate_asset`;
  - `preview_ability`: shows the move with its particles and returns captures.
- **Inspection**: `find_animations` and `get_animation_info` (notifies with times and properties, montage slots and sections).

### New skills
- `conan-animation-from-reference`: reference reading, axis calibration, role posing, compare loop, timing rules.
- `conan-custom-attacks-vfx`: vanilla study, playable montage, particles/trails/sound, hooking into game data, limits.

### Other
- `get_server_capabilities` reports Control Rig, Sequencer, notify and Niagara APIs.
- `docs/animation.md` with a complete walkthrough. 14 new tests (88 in total), including the full pipeline on the fake editor.

## 2.0.0 — Mapping, terrain, structures, DataTables, Blueprints, mod workflow and skills
### New: 51 tools (97 in total)
- **Mapping**: `analyze_terrain` (height and slope stats, walkable %, flat build sites, recommendations),
  `sample_terrain`, and `get_map_layout` (density per category, hotspots, empty zones, light budget, spawn clearance).
- **Landscape**: `sculpt_terrain` with raise/lower/flatten/smooth/noise/ramp brushes and falloff, plus
  `paint_landscape_layer`, `export_heightmap`, `import_heightmap` and `get_landscape_info`. Edits run live with the
  native module, or through a 16-bit heightmap PNG in pure Python.
- **Capture**: `capture_map_overview` (top-down image with a pixel→world mapping) and `capture_viewport`, returned as MCP images.
- **Level**: `classify_level_actors`, `find_actors_in_area`, `spawn_actor`, `spawn_actors_batch`, `scatter_actors`,
  `place_actors_along_path`, `duplicate_actors`, `delete_actors` (undoable, protected classes, limits),
  `snap_actors_to_ground`, `validate_placement`, `get/set_actor_property`, `set_actor_folder`, `select_actors` and `focus_viewport`.
- **DataTables**: `get_datatable_row` now returns real data (it was a stub), plus `get_datatable_schema`,
  `search_datatable_rows`, `add/update/duplicate/remove_datatable_row` and `export/import_datatable`.
  Tables outside `/Game/Mods` are protected.
- **Blueprints**: richer `get_blueprint_info` and `get_blueprint_variables`, plus `compile_blueprint`, `add_blueprint_variable`,
  `set_blueprint_default`, `add_blueprint_component`, `reparent_blueprint` and `list_blueprint_graphs`.
- **Mod**: `create_mod_structure`, `validate_assets` (broken references), `audit_mod` (release checklist and score),
  `get_asset_referencers`, `list_dirty_packages`, `save_all_dirty`, `rename_asset` and `delete_asset` (DESTRUCTIVE).
- **System**: `get_server_capabilities`, `undo`, `redo` and `get_output_log`.
- `create_blueprint` accepts Blueprint or `/Script/` parents. `create_datatable` accepts `/Script/` row structs and `copy_struct_from`.
- `set_actor_transform` supports relative moves.

### New: skills
- Seven playbooks in `skills/`, served as MCP prompts and installable as Claude Code / Antigravity skills:
  `conan-map-design`, `conan-landscape-sculpting`, `conan-structures`, `conan-items-recipes`,
  `conan-blueprint-authoring`, `conan-mod-release` and `conan-mcp-safety`.

### Architecture
- The 2,700-line `conan_mcp_server.py` is split into the `conan_mcp` package (`core/`, `tools/`, `mapping/`).
  `conan_mcp_server.py` remains as a compatible entry point.
- Hot reload preserves sessions and state across every module.
- Deferred (multi-frame) tool results and MCP image content.
- Path validation now covers nested arguments and lists.
- The hard-coded `C:\Program Files\...` toolset paths are replaced by the engine dir (and `CONAN_MCP_EXTRA_PATHS`).
- Optional C++ module `ConanMCPNative` (see `docs/native_module.md`): live sculpting and painting, exact Blueprint
  details and compiler messages. Not enabled by default.
- Legacy `Source/ConanMCP` build rules gained the missing `Sockets` and `Networking` dependencies. The module is still
  not listed in the `.uplugin`.

### Tooling
- `tests/fake_unreal.py` plus 39 tool tests (74 in total); CI runs ruff and checks that `docs/tools.md` is up to date.
- `docs/tools.md` is generated by `scripts/generate_tool_docs.py`. New: `docs/skills.md` and `docs/native_module.md`.

## 1.1.1 — Security & protocol hardening
### Security
- Reject requests with non-loopback `Origin`/`Host` headers; removed wildcard CORS (a web page could previously reach `execute_python`).
- `execute_python` is now `DESTRUCTIVE` and disabled unless `CONAN_MCP_ENABLE_DESTRUCTIVE=1`.
- Package-path validation (`/Game`, `/Engine`, `/ConanSandbox`, no traversal) on every tool and the `conan://asset/` resource.
- Bearer token compared in constant time; request bodies capped at 1 MB.
### Protocol
- SSE transport now follows the 2024-11-05 spec: `POST /messages?sessionId=` returns `202` and the reply is delivered on the SSE stream.
- Game Thread timeout unified at 30 s (`CONAN_MCP_TIMEOUT`); timed-out tasks are cancelled instead of running later.
- Thread-safe request/error counters; `init_unreal.py` honours `CONAN_MCP_HOST` / `CONAN_MCP_PORT`.
### Quality
- Tool arguments are now validated against each tool's `inputSchema` (required, type, enum, min/max) before execution.
- `tools/list` exposes MCP `annotations` (`readOnlyHint`, `destructiveHint`, ...).
- Hot reload (`reload_server`, `conan/reload`) shares one implementation and preserves SSE sessions, queue, counters and ticker.
- Docs aligned to 46 tools / version 1.1.1.
### Other
- The native C++ server no longer auto-starts by default (it shared port 8123 with the Python server).
- Added `pytest` suite (`tests/`) and GitHub Actions CI.
