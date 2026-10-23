---
name: conan-blueprint-authoring
description: Inspect, create and modify Blueprints in the Conan Exiles DevKit with ConanMCP (deep info, variables, defaults, components, reparenting, compile with errors). Use for any Blueprint question or change.
---

# Blueprint authoring

## Inspect first
- `find_blueprint` / `find_assets` (class `Blueprint`) to locate it.
- `get_blueprint_info`: parent class, variables (type, default, current class default value), components,
  graphs and interfaces. With the native module the details are exact (types, flags, categories).
- To extend game behaviour, **subclass** the Conan Blueprint (`create_blueprint` with `parent_class` set
  to its generated class path) instead of editing the original.

## Change
- New Blueprint: `create_blueprint` under `/Game/Mods/<Mod>/Blueprints`, name prefixed `BP_`.
- Variables: `add_blueprint_variable` (`type`: bool, int, float, string, name, text, vector, rotator, transform,
  object/class/struct with `sub_type`; `container: array` for arrays).
- Defaults: `set_blueprint_default` with `values: {Var: value}`. Works for inherited properties as well.
- Components: `add_blueprint_component` (`StaticMeshComponent`, `PointLightComponent`, `BoxComponent`,
  `AudioComponent`, ...) with an optional `parent`.
- Parent swap: `reparent_blueprint` (risky: check variables and graph references afterwards).
- Every change recompiles; always read the `compile` result. On errors use `get_output_log`
  (`category: LogBlueprint`, `min_level: warning`) and fix before continuing.

## Limits (be honest with the user)
- Node graphs (wiring, adding K2 nodes) cannot be edited reliably through the Python API. Describe the exact
  nodes and connections for the user to add, or move the logic into variables, components and defaults.
- `execute_python` is disabled by default (DESTRUCTIVE); do not ask the user to enable it just to work around a limit.

## Finish
`compile_blueprint` with `save: true`, then `validate_assets` on the folder.
