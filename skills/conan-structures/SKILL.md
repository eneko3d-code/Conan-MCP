---
name: conan-structures
description: Identify, add, move, replace and remove structures and props in a Conan Exiles map with ConanMCP (classify, area queries, spawn, scatter, path placement, snap to ground, delete with undo). Use when the user wants to clean up, rebuild, decorate or populate an area.
---

# Working with structures and props

## Identify
- `classify_level_actors` (optionally with `area`) gives counts per category and examples:
  structure, spawner, resource, foliage, light, water, volume, static_mesh, blueprint...
  Categories are name-based heuristics: **look at the examples** before acting on a category.
- `find_actors_in_area` with `area: {center, radius}` or `{min, max}`, plus `category`, `class_filter`,
  `name_filter`, `folder` or `tag`, lists exactly what is there (use `include_bounds` for sizes).
- `get_actor_properties` and `get_asset_info` tell you which mesh/blueprint an actor uses, so you can place more of the same.

## Remove
1. Build the selection with filters; preview with `delete_actors` `dry_run: true`.
2. Show the user the list when it is more than a handful of actors.
3. Run it. It is one transaction: `undo` restores everything.
Landscape, WorldSettings, foliage and other critical actors are protected unless `allow_protected` is set:
do not set it unless the user explicitly asks.

## Place
- Single item: `spawn_actor` with `asset_path` (or `class_name`), `snap_to_ground: true`; add
  `align_to_ground` for rocks and ruins on slopes but not for buildings or walls, which must stay upright.
- Several specific items: `spawn_actors_batch` (one undo step).
- Natural distribution (rocks, trees, ruins, resource nodes): `scatter_actors` with `min_distance`,
  `max_slope` (≈25 for buildings, 35 for props), `scale_min/max` and a `seed`. Always `dry_run` first.
- Lines (walls, fences, torches along a road): `place_actors_along_path` with `spacing` equal to the mesh length;
  `yaw_offset` fixes meshes whose forward axis is not +X.
- Copies of an existing layout: `duplicate_actors` with an `offset`.

## Replace (swap a prop for another)
Find the old actors → record their transforms (`find_actors_in_area`) → `spawn_actors_batch` with the new
asset at the same transforms → `delete_actors` on the old ones → `validate_placement`.

## Always finish with
- `validate_placement` on the area, then `snap_actors_to_ground` for floating/buried results.
- Folders and labels: `set_actor_folder` into `Zones/<Zone>/<Type>`.
- A `capture_viewport` (after `focus_viewport`) or `capture_map_overview` to verify visually.
