---
name: conan-landscape-sculpting
description: Sculpt and paint Conan Exiles DevKit landscapes with ConanMCP brushes (raise, lower, flatten, smooth, noise, ramp, layer paint) safely, natively or through a heightmap PNG. Use for any terrain edit request.
---

# Landscape sculpting with ConanMCP

## Pick the backend
Call `get_landscape_info`:
- `editing_backend: native`: `sculpt_terrain` / `paint_landscape_layer` edit the landscape directly inside an undoable transaction.
- `editing_backend: heightmap_file`: ask the user to export the heightmap once:
  Landscape mode → Manage → Export → Heightmap (16-bit PNG) into the folder reported as `heightmap_folder`.
  Then pass `heightmap_file: "<name>.png"` (and `output_file` to keep the original). Chain all strokes on
  the same file, then the user re-imports it (Landscape mode → Import → Heightmap, same resolution).
  Painting layers requires the native module.

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
