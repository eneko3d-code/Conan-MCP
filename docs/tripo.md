# Tripo AI integration

ConanMCP can drive the [Tripo AI](https://www.tripo3d.ai) v3 API from the DevKit. It can:
- generate 3D models from text, one image or several views;
- create concept images;
- re-texture models (PBR);
- retopologise and convert them;
- auto-rig and animate them;
- import the result straight into your mod.

**It only spends credits when you approve it.**

## Setup

1. Create an API key in the Tripo console: <https://developers.tripo3d.com/en/keys>.
2. Set it as a Windows environment variable, then restart the DevKit:
   ```powershell
   setx TRIPO_API_KEY "tsk_your_key_here"
   ```
   The key is read at call time from the environment. It is never written to disk, logged, or returned in tool results.
3. Optional limits:

   | Variable | Default | Meaning |
   |---|---|---|
   | `CONAN_MCP_TRIPO_BUDGET` | `0` (no cap) | Maximum credits the AI may spend in one editor session |
   | `CONAN_MCP_TRIPO_MIN_BALANCE` | `0` | Refuse new tasks when your balance is below this |
   | `CONAN_MCP_TRIPO_DOWNLOAD_HOSTS` | `tripo3d.ai,tripo3d.com` | Hosts results may be downloaded from (HTTPS only) |
   | `CONAN_MCP_TRIPO_BASE_URL` | `https://openapi.tripo3d.com/v3` | API base URL |

4. Check that it works: `get_server_capabilities` should show `tripo.api_key_configured: true`, and
   `tripo_get_balance` should return your credits.

## How spending is controlled

Every `tripo_*` tool that creates a task follows these steps:
1. **Checks your balance first.** With 0 credits, or less than `CONAN_MCP_TRIPO_MIN_BALANCE`, nothing is sent.
2. **Only plans by default.** Without `confirm_spend: true` it returns the parameters, your balance, the session
   budget and, once known, the observed cost of that task type. The `conan-tripo-assets` skill makes the agent
   ask you before confirming.
3. **Enforces the session budget** (`CONAN_MCP_TRIPO_BUDGET`) using the real `credits_consumed` of finished tasks.
4. **Never retries** after "insufficient credits" (Tripo error 2010). Rate limits (429) are retried with backoff.

Tripo freezes credits when a task starts and refunds them when it fails or is cancelled. Tripo does not publish
a price list in its API docs, so the cost is shown after each task finishes (`tripo_get_task`, `tripo_list_tasks`).

## Tools

| Tool | What it does |
|---|---|
| `tripo_get_balance` | Balance, frozen credits, session spend and budget |
| `tripo_text_to_model` / `tripo_image_to_model` / `tripo_multiview_to_model` | Generate a model |
| `tripo_text_to_image` | Concept or reference image (for example `template: t_pose`) |
| `tripo_texture_model` | Re-texture from text, a reference image or multi-view references |
| `tripo_retopology` / `tripo_convert` | Polygon budget, quads, UVs; FBX/GLTF/OBJ/... |
| `tripo_rig_check` / `tripo_rig` / `tripo_retarget` | Auto-rig (`spec: unreal`) and preset animations |
| `tripo_get_task` / `tripo_list_tasks` | Status, previews, outputs, credits |
| `tripo_upload_file` | Upload an image or model from `Saved/ConanMCP` |
| `tripo_import_result` | Download (Tripo hosts only) and import into `/Game/Mods/<Mod>/Tripo/` |

Images you want to use as references go in `Saved/ConanMCP/tripo/inputs/`. Editor captures from
`capture_viewport` and `capture_map_overview` in `Saved/ConanMCP/captures/` work too.

## Example

> "Generate a Stygian sandstone brazier for my mod `DesertKing`, low-poly, and put it next to the temple entrance."

1. `tripo_get_balance`.
2. A plan: `tripo_text_to_model prompt="Stygian sandstone brazier, carved serpents, bronze bowl, weathered, game asset" face_limit=8000`.
3. The agent asks you, then the same call with `confirm_spend: true`.
4. `tripo_get_task wait_seconds=20` until `success`, plus a look at the preview.
5. `tripo_import_result mod_name=DesertKing asset_name=SM_StygianBrazier`.
6. `find_actors_in_area` near the temple, `spawn_actor ... snap_to_ground=true`, then `capture_viewport`.

## Network and security

- The only outbound connections the server makes are to the Tripo API and Tripo download hosts, and only when
  `TRIPO_API_KEY` is set.
- Uploads are limited to files inside `Saved/ConanMCP`. Downloads only go to `Saved/ConanMCP/tripo` and must
  come from HTTPS Tripo hosts.
- Network calls run outside the Game Thread, so the editor never freezes while a task is generating.
- Generated content follows Tripo's terms of service; your mod must still comply with Funcom's modding EULA.

## Status

The integration is tested against a local simulation of the Tripo v3 API (`tests/test_tripo.py`).
The first live run with your key is the real check. Start with a cheap task (low `face_limit`, no texture).
