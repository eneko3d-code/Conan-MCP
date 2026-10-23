---
name: conan-items-recipes
description: Create or change Conan Exiles items, recipes and other DataTable driven content with ConanMCP (find tables, read schema, copy template rows into the mod's table, edit, validate). Use for new weapons, armour, consumables, placeables, recipes or stat tweaks.
---

# Items, recipes and DataTables

Conan's gameplay data lives in DataTables (items, recipes, crafting, loot, spawns...). Table names and
columns differ between DevKit versions, so **discover them, never guess**.

## 1. Find the tables and learn their shape
- `find_conan_datatables` with a query such as `Item`, `Recipe`, `Craft`, `Loot` or `Spawn`.
- `get_datatable_schema` on the table: columns, JSON types, example values and a template row.
- `search_datatable_rows` to find a similar existing row (for example an iron sword when making a new sword),
  using `fields` to keep the answer short.

## 2. Work in the mod's own table, never in base-game tables
- Base-game tables are protected (`allow_base_game_table` is required): editing them breaks other mods and game updates.
- If the mod has no table yet: `create_datatable` under `/Game/Mods/<Mod>/DataTables` using the **same row struct** as the base table.
- Copy the closest base row into the mod table with `duplicate_datatable_row`
  (`destination_path` = the mod table, `new_row_name` = a unique id prefixed with the mod name, `values` = overrides).
- Unique row names: prefix with the mod name (`MyMod_SteelSword`) to avoid clashes with other mods.

## 3. Edit
- `update_datatable_row` deep-merges `values` (nested structs keep their other fields).
- Reference assets (icons, meshes) by full object path, e.g. `/Game/Mods/MyMod/Icons/T_SteelSword.T_SteelSword`.
- Keep numbers in line with comparable vanilla items (damage, weight, durability). Report the deltas you chose.
- For a recipe, make sure its ingredient and result ids exist in the item tables (`get_datatable_row`).
- Bulk changes: `export_datatable` → edit the JSON → `import_datatable` (`mode: merge`). Use `dry_run` before importing.

## 4. Validate
- Re-read the rows with `get_datatable_row`.
- `validate_assets` on the mod folder for broken icon or mesh references.
- `save_asset` (or `save: true` on the write tool) when the user is happy.
- Tell the user how the rows get into the game: the mod's data merging (for example a ModController or
  the DevKit's table merge setup) must include the new table. Check the mod's existing setup rather than assuming.
