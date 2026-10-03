# 3d-art-plugin

Blender addon (Python, `bpy`) that reads the current scene and sends it to `3d-art-api` over socket.io. Cross-repo architecture, shared Key Principles and the Settings Display Model: `../CLAUDE.md` (the documentation hub). This file covers only what's unique to this repo.

## Structure

- `art3d_sync/` — the addon (per-file roles: `docs/file-structure.md`). The folder name must stay a valid Python identifier (no hyphens, no leading digit) — Blender imports it as a module.
- `socket_client.py` is a stdlib-only (`urllib`) Engine.IO v4 / Socket.IO v5 polling client, so the addon needs no pip install (Blender's bundled Python has neither `python-socketio` nor `websocket-client`). One short-lived session per button press, not a persistent connection.
- `blender/` — demo scenes and assets for testing sync, not addon source. Already ~17MB of tracked `.blend`/`.fbx`/texture binaries with no Git LFS — every commit bloats history permanently, so keep new binaries small. `*.blend1` backups are gitignored. `blender/scripts/` holds the headless generators of demo-scene content (run command in each script's docstring).

## Critical Discipline

**Rebuild `art3d_sync.zip` immediately after any source change, and restart Blender after reinstalling — never trust a hot-reinstall** (a running session keeps old modules cached in `sys.modules`, so a stale copy silently reintroduces bugs that look like regressions). Command + reinstall steps: `rebuild-plugin-zip` skill (`.claude/skills/rebuild-plugin-zip/SKILL.md`).

## Conventions

- **Send only fields the browser can actually apply and that affect the result** (`../CLAUDE.md`'s Settings Display Model). Before dropping a field as unused, confirm it's dead in *Blender's own source*, not just unread by the browser yet (e.g. `turbidity`/`ground_albedo` are unused by Blender's own `MULTIPLE_SCATTERING` sky, so `world_sync.py` doesn't send them). The camera, light, render-settings and world `*_sync.py` docstrings list what was audited and deliberately not sent — read them before adding a field.
- One `*_operators.py` + `*_sync.py` pair per sync concern — never append a new concern to an existing file.
- Verify property names/units by introspecting the live `bpy.types.*` of the running Blender version, not from memory or docs.
- Each button is a synchronous operator (Blender's UI blocks for its duration); long work reports through `window_manager.progress_begin/update/end`.
- **Material export**: glTF carries only flat factors or Image Textures; Blender's exporter silently *omits* any procedurally-driven input (an omitted `baseColorFactor` becomes glTF's default white) and ignores the Volume socket. So `gltf_exporter.py` preprocesses the temp duplicate's materials in order: `material_flatten.py` first (`material_bake.py` only handles a Surface that already is one Principled BSDF), then `material_bake.py`, then `material_volume.py` (roles: `docs/file-structure.md`). Find the Principled by walking from Material Output's Surface (`shader_bake.find_principled_surface`), never "the first Principled by type". Fidelity tests and fixture regeneration (after changing any `material_*.py` or `shader_bake.py`): `../3d-art-web/test/material/README.md`.
- **Coat**: Blender's clearcoat export never carries Coat IOR or Tint and can omit a near-default roughness, so `material_coat.py` reads the coat constants before the export and completes the GLB after it (`extras.coat`, the omitted roughness; wire shape: `../docs/sync-protocol.md`). Coat state and constants are judged on the InlineShaderNodes tree the exporter reads (`material_coat.inlined_principled`), never the raw node tree. Base-channel bakes run inside `shader_bake.coat_disabled()`, which keeps the coat out of them (why: its docstring).

## Doc Map

| File | Load it when… |
|---|---|
| `docs/file-structure.md` | navigating `art3d_sync/` or deciding where a new file belongs |
| `../docs/sync-protocol.md` | the wire payloads this plugin builds, transform/axis/rotation rules, project-room handshake |
| `../3d-art-web/test/material/README.md` | changing material export |
| `../docs/tech-decisions.md` | cross-repo architecture facts |
| `../CLAUDE.md` | cross-repo architecture, product vision, shared principles |
