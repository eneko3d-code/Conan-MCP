---
name: conan-map-design
description: Design, review or extend a Conan Exiles map with the ConanMCP tools: analyze terrain and layout, plan zones, block out, place content and validate. Use whenever the user asks to build, fix, populate or judge a map, a region, a POI or a level layout.
---

# Conan Exiles map design with ConanMCP

You are acting as a level designer working in the live DevKit editor. Never place or sculpt
blind: **measure → plan → change in small undoable steps → look → validate**.

## 0. Start of every map task
1. `get_server_capabilities`: is the native module there (in-editor sculpting/painting), or only the heightmap-file workflow?
2. `get_current_level`, `get_landscape_info`: map name, landscape origin, scale and extent (all coordinates are world cm; X is north, Y is east, Z is up).
3. `capture_map_overview` of the whole landscape: the image comes with a pixel→world formula. Use it to name places by coordinates.
4. `analyze_terrain` (resolution 32–64) and `get_map_layout` (cells 8–16): heights, slopes, flat build sites, actor density, empty zones, recommendations.
5. `classify_level_actors`: what already exists (structures, spawners, resources, lights, water, foliage).

Summarize what you found in a short **map brief** before proposing changes.

## 1. Plan before touching anything
Write a zone plan the user can approve:
- **Zones**: biome/theme, purpose (start area, travel, resources, danger, landmark, settlement, boss arena), rough bounds in world cm.
- **Routes**: the main paths between zones, as polylines. Every route must stay walkable.
- **POIs**: each with coordinates, purpose, size and what the player gets there.
- **Budget**: rough actor and light counts per zone.

Ask for confirmation on large changes (whole-map sculpting, deleting more than ~20 actors, new zones).

## 2. Design rules (your own judgement, apply them every time)
**Traversal**
- Walkable slope ≤ 35° (Conan characters struggle above it); main roads ≤ 20°.
- Cliffs > 50° are barriers: use them on purpose to funnel players, never across a required route without a ramp.
- Leave at least 6–8 m of width for main paths and around entrances, gates and stairs.

**Layout and pacing**
- Points of interest roughly every 150–300 m of travel; never leave large empty cells (see `get_map_layout.empty_cells`) without intent.
- Always give the player a landmark in view: a tall structure, a peak, a statue or a fire visible from afar.
- Alternate open and closed spaces; break long sightlines with terrain or structures (also good for performance).
- Danger escalates away from the start area; resources scale with danger.

**Spawns and safety**
- Keep 15–20 m clear around player spawns and NPC spawners of clutter; NPCs need navigable flat ground (slope ≤ 25°).
- Do not overlap hostile spawners with player start or crafting zones.
- Water: shores need a walkable exit every ~50 m; check `below_water_percent` when you change heights near water.

**Placement quality**
- Nothing floating or buried: run `validate_placement` after any placement and fix with `snap_actors_to_ground`.
- Structures sit on flat pads: flatten first (`sculpt_terrain operation=flatten`) then place.
- Vary repeated assets: random yaw, scale 0.85–1.15, min spacing (`scatter_actors`).
- Group content in Outliner folders per zone (`folder: "Zones/<Zone>/<Type>"`) and use readable labels.

**Performance budget (per 8x8 layout cell on a typical map)**
- Lights: keep under ~12 per cell, most without shadows; `get_map_layout` warns about hotspots.
- Avoid clusters more than ~4x the mean density; prefer fewer, larger meshes.

## 3. Execute in small, reversible steps
- Terrain first (see the `conan-landscape-sculpting` skill), then large structures, then props/resources, then lights/decals.
- Every write supports `dry_run: true`: preview first, then run for real.
- One transaction per logical step; if the result is worse, call `undo`.
- After each step: `capture_map_overview` of the area (or `focus_viewport` + `capture_viewport`) and look at it critically.

## 4. Validate and report
1. `validate_placement` on the zone (fix floating/buried/overlaps).
2. `analyze_terrain` again on routes: walkable_percent should not drop.
3. `get_map_layout`: no new hotspots, empty zones filled on purpose.
4. Final overview capture; `list_dirty_packages`, then `save_current_level` / `save_all_dirty` when the user agrees.
5. Report: what changed (with coordinates), why, what to test in game (PIE), and what you would do next.
