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
├── gltf_exporter.py             # one object → .glb bytes via a temp unparented/identity-transform duplicate; runs the material_* preprocessing on it
├── material_flatten.py          # Surface that isn't one directly-wired Principled BSDF (e.g. Mix Shader) → one synthetic Principled
├── material_bake.py             # Cycles-bakes procedural Base Color/Roughness/Normal/Emission inputs to image textures (the exporter omits them otherwise)
├── material_volume.py           # approximates Volume shaders (KHR_materials_volume nodes, or an alpha-blend fallback) — the exporter ignores the Volume socket
├── shader_bake.py               # shared bake plumbing: find_principled_surface() (the Principled actually wired to Material Output), emission-rewire socket bake
├── object_id.py                 # resolve_stable_ids(objects): batch-resolves `art3d_id` (custom property, survives renames) so a duplicate colliding with its original is decided deterministically by name; get_existing_id(obj) is the side-effect-free lookup for the delete diff
├── sent_ids.py                  # ids included in the last successful blender-sync (Scene property art3d_sent_ids) — operators.py diffs it to detect deletions
├── world_operators.py           # ART3D_OT_send_world — emits "blender-world-sync"
├── world_sync.py                # active World's Sky Texture node → sky payload
├── world_hdri_operators.py      # ART3D_OT_send_world_hdri — emits "blender-world-hdri-sync"
├── world_hdri_sync.py           # Material Preview's HDRI: the World's Environment Texture image re-encoded to Radiance HDR, or, if none is assigned, the Sky Texture baked to an equirect HDRI
├── light_operators.py           # ART3D_OT_send_lighting (scope 'selected'|'all') — emits "blender-lighting-sync"
├── light_sync.py                # Light objects → world-space position + unit direction (computed in Python), type/color/energyWatts/castShadow/shadowSoftSize/spot/area fields; same stable id as scene_graph.py
├── render_settings_operators.py # ART3D_OT_send_render_settings — emits "blender-render-settings-sync"
├── render_settings_sync.py      # exposure, viewTransform, resolutionX/Y (resolution only for the synced camera's aspect/FOV)
├── camera_operators.py          # ART3D_OT_send_camera (scope 'selected'|'all') — emits "blender-camera-sync"
├── camera_sync.py               # Camera objects → optics only (lens/sensor/clip/ortho); transform stays scene_graph.py's job
└── socket_client.py             # stdlib-only Engine.IO/Socket.IO polling client — emit_once(..., auth={token, projectId}) sends auth in the CONNECT packet

blender/                         # demo scenes/assets for testing sync — not addon source
```

Shipped as `art3d_sync.zip` (gitignored, built locally) — rebuild/reinstall rule: `CLAUDE.md`'s Critical Discipline. Payload shapes, handshake and timeouts: [`../../docs/sync-protocol.md`](../../docs/sync-protocol.md).
