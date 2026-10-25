---
name: conan-landscape-sculpting
description: Sculpt and paint Conan Exiles DevKit landscapes with ConanMCP brushes (raise, lower, flatten, smooth, noise, ramp, layer paint) safely, live through render targets (with backups and verification) or through a heightmap PNG. Use for any terrain edit request.
---

# Landscape sculpting with ConanMCP

## Pick the backend
Call `get_landscape_info` and read `editing_backend`:
- `render_target` (the usual one in the Conan DevKit, pure Python):
  - `sculpt_terrain`, `export_heightmap` and `import_heightmap` edit the landscape live;
  - every write first saves a full PNG backup (`list_heightmap_backups`), then re-exports and checks every height;
  - if the result is not exact, it restores the backup automatically and reports an error.
- `native`: only if the optional C++ module is loaded. The Conan DevKit cannot compile it.
- `heightmap_file`: last resort. Export the heightmap once from Landscape mode (Manage → Export → Heightmap,
  16-bit PNG) into `heightmap_folder`, pass `heightmap_file: "<name>.png"`, then re-import it by hand.

**First time on a level, or after a DevKit update:** run `test_landscape_backend write_test=true` on a test
level (for example `/Game/Dev/AlmostEmpty`). Continue only if `result: ok` and `altered_heights: 0`.
Note `read_s`, which tells you how long each stroke will take.

**Reading the results of a write:**
- `read_attempts > 1`: the first exports of a session can come back empty while the editor compiles the
  export shader. The tool re-exports on later ticks, and **writes nothing** until a read is valid.
- `members`: the landscape actors that were edited. Separate landscapes or tiles are never merged.
- `trace_check`: exported heights compared with line traces on the landscape before writing.
  - `ok`: they match.
  - `mismatch`: the write was refused.
  - `insufficient`: there were not enough visible landscape points, for example because they are covered by
    structures or have no collision. Look at the result yourself with `capture_map_overview` before continuing.
- `trace_check_after` and `verified`: checks after writing. On a mismatch the backup is restored automatically.
  - `verified: "inconclusive"`: the landscape could not be re-read. Check it visually and use
    `restore_heightmap_backup` if it looks wrong.

**Undo:** `undo` (Ctrl+Z) may revert an import. The guaranteed way back is `restore_heightmap_backup` with
the `backup` file named in each stroke's result.

**Painting layers without the native module:** `paint_landscape_layer` can only **replace a whole layer**,
because the current weights cannot be read. Use `replace_layer: true` only for a new or empty layer, or to repaint a
layer completely, and tell the user before doing it.

## Units and coordinates
- `center`, `end`, `radius`, `amount`, `target_z`, `noise_scale` are **world centimetres**.
- Height precision: 1 height unit = scale.z / 128 cm (≈0.78 cm at the default scale of 100).

## Brushes
| operation | key args | use it for |
|---|---|---|
| raise / lower | amount, radius, falloff | hills, mounds, pits, riverbeds |
| flatten | target_z (default: height at centre), radius | building pads, arenas, camps, roads |
| smooth | iterations (1–5), radius | soften harsh edges after other strokes |
| noise | amount (50–300 cm), noise_scale (1000–4000 cm), seed | break up flat or artificial looking ground |
| ramp | end {x, y, z}, start_z, radius = half width | walkable roads up slopes, bridge approaches |

`falloff` 0..1 is the soft edge fraction (0.5 is natural; 0 is a hard edge for pads).

## Safe workflow
1. Measure: `sample_terrain` / `analyze_terrain` around the target.
2. `dry_run: true` first, then check `stats.max_delta_cm` and `changed_vertices` make sense.
3. Apply. Prefer several moderate strokes (≤ 5 m each) over one huge one; keep radius ≤ 50 m per call.
4. Smooth the borders of flatten/ramp strokes with a slightly larger `smooth` pass.
5. Re-check: `analyze_terrain` (slopes on routes ≤ 35°, walkable % stable), `validate_placement` for actors
   that are now floating or buried, then `snap_actors_to_ground` for them.
6. Look at it: `capture_map_overview` of the area (mode `base_color` gives a clean read of shapes).
7. If it looks wrong: `undo` (native) or keep the previous PNG (file workflow).

## Recipes
- **Building pad**: flatten (falloff 0.2, radius = footprint + 3 m) → smooth ring (radius + 4 m, iterations 2).
- **Road up a hill**: ramp from the bottom to the top (half width 400–600 cm), keep the gradient ≤ 20°:
  rise / run ≤ 0.36. Split long climbs into switchbacks.
- **Natural hill**: raise (falloff 0.8) → noise (amount 100, scale 2500) → smooth (iterations 1).
- **Lake bed**: lower inside the shoreline, keep a walkable beach (slope ≤ 20°) on at least one side.

Paint after sculpting: rock on slopes > 35°, dirt/sand on paths and shores, grass on flats
(`paint_landscape_layer`, `strength` 0.5–1, layer names from `get_landscape_info`).
