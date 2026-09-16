# 3d-art-plugin

Blender addon (Python, `bpy`) that reads the current scene and streams it to `3d-art-api` over socket.io. Cross-repo architecture, product vision, shared Key Principles (KISS/DRY, naming length, "ask don't pick silently", etc.): `../CLAUDE.md` — that repo is the documentation hub for all three repos. This file covers only what's unique to this repo.

## Structure

`blender/` — small demo scenes and reference assets used to test/demonstrate sync (not addon source). Currently includes some heavy binaries (textures, a duplicate `.blend.zip` alongside its already-extracted folder) — worth trimming to genuinely small files before this grows further; large binaries here have no Git LFS in place yet, so they bloat this repo's history permanently once committed.

`art3d_sync/` (must be a valid Python identifier — no hyphens, no leading digit — Blender imports it as a module):

- `__init__.py` — `bl_info` + `register()`/`unregister()`
- `panel.py` — N-panel UI (General Settings / Objects / Lighting sections)
- `constants.py` — `SERVER_URL`, shared across operator modules
- `operators.py` + `scene_graph.py` + `gltf_exporter.py` — object/scene sync (`ART3D_OT_send_scene`, `scope: 'selected'|'all'`)
- `world_operators.py` + `world_sync.py` — sky (`ART3D_OT_send_world`)
- `light_operators.py` + `light_sync.py` — lighting (`ART3D_OT_send_lighting`)
- `render_settings_operators.py` + `render_settings_sync.py` — render settings (`ART3D_OT_send_render_settings`)
- `socket_client.py` — stdlib-only Engine.IO/Socket.IO v4 polling client (no pip install — Blender's bundled Python has neither `python-socketio` nor `websocket-client`)

Full annotated tree: `docs/file-structure.md`.

## Critical Discipline

**Rebuild `art3d_sync.zip` immediately after any source change, and restart Blender after reinstalling — never trust a hot-reinstall.**

```bash
rm -f art3d_sync.zip && zip -r art3d_sync.zip art3d_sync -x "*.pyc" -x "__pycache__/*"
```

An already-running Blender session can have old modules cached in `sys.modules` even after the files on disk change — a stale installed copy silently reintroduces bugs that look like regressions.

## Conventions

- **Only send fields the browser side can actually apply and that affect the rendered result** — see `../docs/settings-display-model.md`. Before dropping a field as unused, confirm it's genuinely dead in *Blender's own source*, not just unread by the browser yet (e.g. `turbidity`/`ground_albedo` were confirmed hardcoded-unused in Blender's own `MULTIPLE_SCATTERING` C++ source before being dropped from `world_sync.py`).
- Each sync concern gets its own `*_operators.py` + `*_sync.py` pair, not appended to an existing file — one-file-one-responsibility.
- Real Blender field values only — verify property names/units by introspecting the live Blender API (`bpy.types.*` on the actual running version), not from memory or potentially-stale documentation.
- Each button press is a synchronous operator — Blender's UI blocks naturally for its duration; `window_manager.progress_begin/update/end` drives the native progress bar.

## Doc Map

| File | Load it when… |
|---|---|
| `docs/file-structure.md` | navigating this repo's `art3d_sync/` |
| `../docs/sync-protocol.md` | the wire payload shapes this plugin builds |
| `../docs/tech-decisions.md` | current sync-protocol facts (per-object export, no axis conversion, quaternions, etc.) |
| `../CLAUDE.md` | cross-repo architecture, product vision, Tech Stack, shared principles |
