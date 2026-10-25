# Optional native module (`ConanMCPNative`)

> **The Conan Exiles DevKit cannot build this module.** It ships without the engine headers
> (`Engine/Source/Runtime/Landscape/...` is missing), so `ConanMCP.uplugin` deliberately has no `Modules`
> section and no binaries are shipped. Landscape editing in the DevKit uses the pure-Python **render_target**
> backend instead: live sculpting, export/import, backups and verification. This module only matters if you
> use ConanMCP in a full Unreal Engine build from source.

Everything in ConanMCP works **without compiling anything**: the server is pure Python. In a source build of the
engine, the optional C++ module `Source/ConanMCPNative` adds:

| Feature | Without the module | With the module |
|---|---|---|
| `sculpt_terrain` | Live, through render targets (backup + verification) | Live, region-only, undoable with Ctrl+Z |
| `paint_landscape_layer` | Replaces a whole layer only (`replace_layer=true`) | Blends into existing weights |
| `export_heightmap` / `import_heightmap` | Through render targets | Direct |
| `compile_blueprint` | Status + matching Output Log lines | Exact compiler errors and warnings |
| `get_blueprint_info` | Best-effort variable types | Exact pin types, flags, node titles per graph |
| `add_blueprint_variable` | Needs `BlueprintEditorLibrary.add_member_variable` | Always available |
| `undo` / `redo` | `TRANSACTION UNDO` console command | Direct editor call |

Python detects the module by itself (`get_server_capabilities` → `native_library: true`).

## Enabling it

> Requires Visual Studio 2022 with the "Game development with C++" workload, and a DevKit that lets you
> compile plugins. If it fails to build, remove the `Modules` block again: the Python server keeps working.

1. Add this block to `ConanMCP.uplugin`, at the top level (for example after `"CanContainContent": true,`):

   ```json
   "Modules": [
     { "Name": "ConanMCPNative", "Type": "Editor", "LoadingPhase": "Default" }
   ],
   ```

   Only `ConanMCPNative` is listed on purpose. The legacy `Source/ConanMCP` module (the old C++ HTTP server)
   stays disabled because the Python server replaces it.

2. Build it, either:
   - **The plugin is inside a project's `Plugins/` folder**: open the DevKit. When it asks to rebuild the
     missing modules, answer *Yes*.
   - **The plugin is inside the engine's `Plugins/` folder**: build it with UAT, then copy the packaged result over the plugin:

     ```bat
     "<DevKit>\Engine\Build\BatchFiles\RunUAT.bat" BuildPlugin ^
       -Plugin="<DevKit>\...\Plugins\ConanMCP\ConanMCP.uplugin" ^
       -Package="C:\Temp\ConanMCPBuild" -TargetPlatforms=Win64
     ```

3. Restart the DevKit and call `get_server_capabilities`. It should report `native_library: true` and list the
   functions of `ConanMCPEditorLibrary`.

## Status

The native code targets UE 5.x (`FLandscapeEditDataInterface`, edit layers, `FKismetEditorUtilities`). It has
**not been compiled against the Conan Exiles DevKit yet**. If your build reports errors, open an issue with the
compiler output. The usual fixes are small API renames between engine versions.

Landscapes that use **edit layers** need the target layer selected in Landscape mode before sculpting;
the tool returns a clear error otherwise.
