# 3d-art-plugin

Blender addon (Python, `bpy`) that reads the current scene and sends it to `3d-art-api` over HTTP. Cross-repo architecture, shared Key Principles and the Settings Display Model: `../CLAUDE.md` (the documentation hub). This file covers only what's unique to this repo.

## Structure

- `art3d_sync/` — the addon (per-file roles: `docs/file-structure.md`). The folder name must stay a valid Python identifier (no hyphens, no leading digit) — Blender imports it as a module.
- **Connection** — plain HTTP, stdlib only (`urllib`; Blender's Python has no socketio/requests), no socket at all, so a main thread stalled in a bake can't drop a connection. A computer connects once: Connect account runs a device-code pairing approved in the browser, and the device token lands in `art3d/credentials.json` under the user config dir, keyed by server, never in a .blend. A daemon worker thread (`connection.py`) heartbeats every 3 s and does the pairing and the project list; `runtime.py`'s 0.5 s timer feeds it the active scene's project and turns its results into the status (`status.py`) that drives the panel, the status-bar item and every Send's poll(). A Send announces itself with a heartbeat, then POSTs its payload to `/api/editor/sync`. Each scene keeps its own project binding (`project.py`), picked from the account's projects.
- `blender/` — demo scenes and assets for testing sync, not addon source. Already ~17MB of tracked `.blend`/`.fbx`/texture binaries with no Git LFS — every commit bloats history permanently, so keep new binaries small. `*.blend1` backups are gitignored. `blender/scripts/` holds the headless generators of demo-scene content (run command in each script's docstring).

## Critical Discipline

**Rebuild `art3d_sync.zip` immediately after any source change, and restart Blender after reinstalling — never trust a hot-reinstall** (a running session keeps old modules cached in `sys.modules`, so a stale copy silently reintroduces bugs that look like regressions). Command + reinstall steps: `rebuild-plugin-zip` skill (`.claude/skills/rebuild-plugin-zip/SKILL.md`).

## Conventions

- **Send only fields the browser can actually apply and that affect the result** (`../CLAUDE.md`'s Settings Display Model). Before dropping a field as unused, confirm it's dead in *Blender's own source*, not just unread by the browser yet (e.g. `turbidity`/`ground_albedo` are unused by Blender's own `MULTIPLE_SCATTERING` sky, so `world_sync.py` doesn't send them). The camera, light, render-settings and world `*_sync.py` docstrings list what was audited and deliberately not sent — read them before adding a field.
- One `*_operators.py` + `*_sync.py` pair per sync concern — never append a new concern to an existing file.
- Verify property names/units by introspecting the live `bpy.types.*` of the running Blender version, not from memory or docs.
- Each button is a synchronous operator (Blender's UI blocks for its duration); long work reports through `window_manager.progress_begin/update/end`.
- **Never call `bpy` from a thread.** The connection worker touches only its lock-guarded state and the credentials file; `runtime.py` (main thread) moves data between it and Blender. Network calls on the main thread are the synchronous ones a click waits for anyway (the Send upload, New project, the dev token).
- **Material export**: glTF carries only flat factors or Image Textures; Blender's exporter silently *omits* any procedurally-driven input (an omitted `baseColorFactor` becomes glTF's default white) and ignores the Volume socket. So `gltf_exporter.py` preprocesses the temp duplicate's materials in order: `material_flatten.py` first (`material_bake.py` only handles a Surface that already is one Principled BSDF), then `material_bake.py`, then `material_volume.py` (roles: `docs/file-structure.md`). Find the Principled by walking from Material Output's Surface (`shader_bake.find_principled_surface`), never "the first Principled by type". Fidelity tests and fixture regeneration (after changing any `material_*.py` or `shader_bake.py`): `../3d-art-web/test/material/README.md`.
- **Coat**: Blender's clearcoat export never carries Coat IOR or Tint and can omit a near-default roughness, so `material_coat.py` reads the coat constants before the export and completes the GLB after it (`extras.coat`, the omitted roughness; wire shape: `../docs/sync-protocol.md`). Coat state and constants are judged on the InlineShaderNodes tree the exporter reads (`material_coat.inlined_principled`), never the raw node tree. Base-channel bakes run inside `shader_bake.coat_disabled()`, which keeps the coat out of them (why: its docstring).

## Headless

Scripts run with `blender -b` get no timers; `art3d_sync.headless` does the timer's job in a loop (the worker thread still beats):

```bash
ART3D_SERVER_URL=http://localhost:3600 ART3D_TOKEN=art3d_… XDG_CONFIG_HOME=/tmp/art3d-test \
  blender -b scene.blend --python script.py
```

```python
import bpy
from art3d_sync import headless  # enabled add-on, or sys.path.insert(0, "<repo>"); import art3d_sync; art3d_sync.register()

headless.bind_project("<project id>")
status = headless.wait_ready(30)  # READY once a browser has the project open; else the last status
bpy.ops.art3d.send_scene(scope="all")
```

`ART3D_TOKEN` is used instead of the credentials file and never written; a DEV_TOOLS server issues one with `POST /api/dev/device-token {"user": "claude"}`. A temp `XDG_CONFIG_HOME` keeps a test's pairing away from the real credentials file. `headless.wait_until(predicate)` waits for any other status (e.g. a pairing code).

## Doc Map

| File | Load it when… |
|---|---|
| `docs/file-structure.md` | navigating `art3d_sync/` or deciding where a new file belongs |
| `../docs/sync-protocol.md` | the wire payloads this plugin builds, transform/axis/rotation rules, the editor↔server connection |
| `../3d-art-web/test/material/README.md` | changing material export |
| `../docs/tech-decisions.md` | cross-repo architecture facts |
| `../CLAUDE.md` | cross-repo architecture, product vision, shared principles |
