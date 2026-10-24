# Skills

ConanMCP ships its own know-how as **skills** in `skills/<name>/SKILL.md`. Each one is a short playbook:
which tools to call, in which order, and the design or safety rules to apply.

| Skill | Use it for |
|---|---|
| `conan-map-design` | Building, extending or reviewing a map: analyze → plan → block out → place → validate, with level-design rules (traversal slopes, POI spacing, spawn safety, landmarks, performance budgets) |
| `conan-landscape-sculpting` | Terrain edits: brushes, units, safe workflow, recipes (building pads, roads, hills, lakes), layer painting |
| `conan-structures` | Identifying, removing, placing, replacing and cleaning up structures and props |
| `conan-items-recipes` | New or changed items, recipes and other DataTable content, kept inside the mod's own tables |
| `conan-blueprint-authoring` | Inspecting and modifying Blueprints, and what is not possible through the API |
| `conan-animation-from-reference` | Turning an image or description into an animation with Control Rig: read the pose, calibrate axes, key by bone roles, compare captures, time, bake |
| `conan-custom-attacks-vfx` | Making attacks/abilities playable: reuse vanilla damage windows, add Niagara/Cascade bursts, trails and sounds, montage, hook into game data |
| `conan-tripo-assets` | Generating, texturing, optimising, rigging and importing assets with Tripo AI, spending credits only with approval |
| `conan-mod-release` | Mod folder layout and the pre-release audit checklist |
| `conan-mcp-safety` | Ground rules: capabilities, dry runs, undo, limits, saving |

## Any MCP client (Cursor, Antigravity, Claude...)

The server publishes every skill as an **MCP prompt** with the same name (`prompts/list`, `prompts/get`), with an
optional `goal` argument. Pick it from your client's prompt menu, or ask the agent to load it. Nothing to install.

## Claude Code

Copy (or symlink) the folders into your skills directory:

```powershell
# whole machine
xcopy /E /I "<Plugins>\ConanMCP\skills\*" "%USERPROFILE%\.claude\skills\"
# or just one project
xcopy /E /I "<Plugins>\ConanMCP\skills\*" "<your project>\.claude\skills\"
```

Claude Code loads a skill automatically when your request matches its description.

## Google Antigravity and other SKILL.md-compatible agents

Point the agent's skills or knowledge folder at `ConanMCP/skills`, or copy the folders into its skills
directory. The files use the standard `name` / `description` frontmatter.

## Writing your own

Add `skills/<your-skill>/SKILL.md` with frontmatter:

```markdown
---
name: your-skill
description: When the agent should use it (one or two sentences).
---
# Instructions...
```

Call `reload_server` (or restart the DevKit) and the new skill appears as an MCP prompt.
