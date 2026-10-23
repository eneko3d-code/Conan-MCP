---
name: conan-mcp-safety
description: Ground rules for driving the Conan Exiles DevKit through ConanMCP without losing work (capabilities, dry_run, undo, limits, saving, security levels). Read it at the start of any session that will modify the editor.
---

# Working safely in the editor

- **Start** with `get_server_capabilities`: it tells you which APIs and native helpers exist and which security
  levels are enabled. Do not call tools whose capability is false; explain the limitation instead.
- **Security levels**: READ_ONLY tools are always allowed. SAFE_WRITE tools change the level or assets but are
  undoable or local. DESTRUCTIVE tools (`execute_python`, `delete_asset`) are off unless the user enables them;
  never push the user to enable them.
- **dry_run first** for every write that touches more than one thing (delete, scatter, batch spawn, sculpt,
  table import). Show the preview when it is large.
- **Undo**: every SAFE_WRITE level/asset edit is one editor transaction. `undo` (or Ctrl+Z) reverts it; `redo` re-applies it.
  Asset deletion and file writes are the exceptions.
- **Limits**: bulk actor edits are capped (`max_count`, server hard limit in capabilities). If a filter matches
  more, narrow it (area, category, folder) instead of raising limits.
- **Base content is read-only by policy**: work inside `/Game/Mods/<Mod>`; base-game DataTables need explicit permission.
- **Files** live only in `<Project>/Saved/ConanMCP/` (heightmaps, captures, table exports). Pass plain file names.
- **Saving**: tools do not save unless asked (`save: true`, `save_asset`, `save_current_level`, `save_all_dirty`).
  Ask before saving maps.
- **Look at your work**: after visual changes, use `capture_viewport` or `capture_map_overview` and check the image yourself.
- **When something fails**: read `get_output_log` (filter by category or `min_level: error`) before retrying,
  and never retry a failing write in a loop.
