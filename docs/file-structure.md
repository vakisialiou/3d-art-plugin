# File Structure — 3d-art-plugin

Load when navigating `art3d_sync/` or deciding where a new file belongs (placement rule: one `*_operators.py` + `*_sync.py` pair per sync concern — `CLAUDE.md`'s Conventions).

```
art3d_sync/                      # addon package (naming rule: CLAUDE.md)
├── __init__.py                  # bl_info + register()/unregister()
├── panel.py                     # N-panel tab "3D Art": Project / General Settings / Objects / Lighting / Camera
├── constants.py                 # SERVER_URL, DEV_TOKEN — shared by all operator modules
├── project.py                   # get_project_id(context) — Scene property art3d_project_id; every send operator refuses to run without it
├── operators.py                 # ART3D_OT_send_scene (scope 'selected'|'all') — emits "blender-sync", appends delete entries
├── scene_graph.py               # objects → entries (id, name, parentId, action, real obj.type, transform from matrix_local, glb only for mesh-convertible types); build_delete_entries()
├── gltf_exporter.py             # one object → .glb bytes via a temp unparented/identity-transform duplicate (its own animation and constraints are cleared: only an armature's action is exported, object-level animation isn't supported); runs the material_* preprocessing on it, then the coat post-pass on the exported GLB
├── material_flatten.py          # Surface that isn't one directly-wired Principled BSDF (e.g. Mix Shader) → one synthetic Principled
├── material_bake.py             # Cycles-bakes procedural Base Color/Roughness/Normal/Emission inputs to image textures (the exporter omits them otherwise); with the coat on (`_coat_bakes`) also Coat Weight/Roughness/Normal, and the base bakes run under shader_bake.coat_disabled()
├── material_coat.py             # coat post-pass on the exported GLB's JSON chunk: extras.coat {ior?, tint?} and the clearcoatRoughnessFactor the exporter omits (it never writes Coat IOR/Tint); owns inlined_principled() (the InlineShaderNodes tree the exporter reads) and has_coat(), which also gate material_bake's coat bakes
├── material_volume.py           # approximates Volume shaders (KHR_materials_volume nodes, or an alpha-blend fallback) — the exporter ignores the Volume socket
├── shader_bake.py               # shared bake plumbing: find_principled_surface() (the Principled actually wired to Material Output), find_active_output() (active output node of a type, else the first; world_sync.py uses it for World Output), emission-rewire socket bake, coat_disabled() (Coat Weight zeroed for the base bakes)
├── object_id.py                 # resolve_stable_ids(objects): batch-resolves `art3d_id` (custom property, survives renames) so a duplicate colliding with its original is decided deterministically by name; get_existing_id(obj) is the side-effect-free lookup for the delete diff
├── sent_ids.py                  # ids included in the last successful blender-sync (Scene property art3d_sent_ids) — operators.py diffs it to detect deletions
├── world_operators.py           # ART3D_OT_send_world — emits "blender-world-sync"; cancels with a WARNING when no Sky reaches the World Output, the sky type isn't Single/Multiple Scattering, or Strength is driven by a graph other than a Value node
├── world_sync.py                # find_world_sky(): the Sky Texture the World really renders, walked from the active World Output's Surface as Cycles evaluates the tree (muted/invalid links dropped), plus its Background/Emission strength → sky payload (sunDisc only under Cycles)
├── world_hdri_operators.py      # ART3D_OT_send_world_hdri — emits "blender-world-hdri-sync"
├── world_hdri_sync.py           # Material Preview's HDRI: the World's Environment Texture image re-encoded to Radiance HDR, or, if none is assigned, the Sky Texture baked to an equirect HDRI
├── light_operators.py           # ART3D_OT_send_lighting (scope 'selected'|'all') — emits "blender-lighting-sync"
├── light_sync.py                # Light objects → world-space position + unit direction (computed in Python), type/color/energyWatts/normalize/castShadow/shadowSoftSize/shadowFilterRadius/spot/area shape+size fields (color and power fold EEVEE's exposure and temperature tint; normalize is sent, not folded in); same stable id as scene_graph.py
├── render_settings_operators.py # ART3D_OT_send_render_settings — emits "blender-render-settings-sync"
├── render_settings_sync.py      # scene color management as the viewport display shader applies it (display device/emulation, view transform, look, exposure, gamma, white balance, curves, dither) + resolutionX/Y and pixelAspectX/Y (resolution and pixel aspect only give the synced camera's frame aspect)
├── curve_tables.py              # view_settings.curve_mapping → the per-channel tables Blender's GPU display shader reads (Combined curve premultiplied into R/G/B); render_settings_sync's `curves`
├── camera_operators.py          # ART3D_OT_send_camera (scope 'selected'|'all') — emits "blender-camera-sync"
├── camera_sync.py               # Camera objects → optics only (lens, sensor size + fit, shift, clip, ortho scale, viewport display size); transform stays scene_graph.py's job
└── socket_client.py             # stdlib-only Engine.IO/Socket.IO polling client — emit_once(..., auth={token, projectId}) sends auth in the CONNECT packet

blender/                         # demo scenes/assets for testing sync — not addon source
└── scripts/                     # headless generators of demo-scene content: add_coat_materials.py (idempotent) adds the Car Paint / Car Paint Worn coat demos to materials-demo.blend and materials/plastic_rubber.blend — run command in its docstring
```

Shipped as `art3d_sync.zip` (gitignored, built locally) — rebuild/reinstall rule: `CLAUDE.md`'s Critical Discipline. Payload shapes, handshake and timeouts: [`../../docs/sync-protocol.md`](../../docs/sync-protocol.md).
