# File Structure — 3d-art-plugin

Read this on demand when navigating this repo's codebase or deciding where a new file belongs.

---

```
art3d_sync/                     # addon package — name must be a valid Python
│                                # identifier (no hyphens, no leading digit),
│                                # since Blender imports it as a module
├── __init__.py                 # bl_info + register()/unregister()
├── panel.py                    # N-panel UI, sectioned: Project / General Settings / Objects / Lighting / Camera
├── constants.py                 # SERVER_URL, DEV_TOKEN — shared by all operator modules
├── operators.py                # ART3D_OT_send_scene (scope: 'selected'|'all') — orchestrates, emits
├── world_operators.py          # ART3D_OT_send_world — orchestrates, emits "blender-world-sync"
├── world_sync.py               # Reads the active World's Sky Texture node → plain-dict sky payload
├── light_operators.py          # ART3D_OT_send_lighting (scope: 'selected'|'all') — orchestrates, emits "blender-lighting-sync"
├── light_sync.py               # Walks Light objects → plain-dict payload, light-data only (color/energy/shadow/...), keyed by the same stable id as scene_graph.py — never resends position/direction
├── render_settings_operators.py # ART3D_OT_send_render_settings — orchestrates, emits "blender-render-settings-sync"
├── render_settings_sync.py     # Reads scene.view_settings (exposure/view transform/look) → plain-dict payload
├── camera_operators.py         # ART3D_OT_send_camera (scope: 'selected'|'all') — orchestrates, emits "blender-camera-sync"
├── camera_sync.py              # Walks Camera objects → plain-dict payload, optics only (lens/sensor/clip/ortho) — no transform, that's scene_graph.py's job
├── scene_graph.py              # Walks selection/scene → objects[] payload entries (id, name, parentId, transform, real obj.type); build_delete_entries() builds the {id, action:'delete'} entries for ids sent_ids.py finds missing
├── object_id.py                # get_stable_id(obj) — persistent per-object UUID (custom property `art3d_id`), survives renames; used by scene_graph.py, light_sync.py, camera_sync.py. get_existing_id(obj) is the same lookup without generating a new id, for sent_ids.py's delete-diff
├── sent_ids.py                 # get/set the set of object ids the last successful blender-sync send included (Scene custom property `art3d_sent_ids`) — operators.py diffs this against the current scene to detect deletions
├── project.py                  # get_project_id(context) — Scene property (art3d_project_id), required by every send operator before it runs
├── gltf_exporter.py            # One object → .glb bytes, via a temp unparented/identity-transform duplicate
└── socket_client.py            # stdlib-only Engine.IO/Socket.IO polling client — emit_once()'s `auth` param carries {token, projectId} in the CONNECT packet

blender/                        # Small demo scenes/assets used to test and demonstrate sync — not addon source
```

Ships zipped as `art3d_sync.zip`, installed via Blender's Preferences → Add-ons → Install from Disk (rebuild/reinstall discipline and the actual command: `CLAUDE.md`'s Critical Discipline). No pip install required — `socket_client.py` speaks the Engine.IO/Socket.IO v4 polling protocol directly over `urllib`, since Blender's bundled Python has no `python-socketio`/`websocket-client`. Each button press opens a short-lived polling session, connects, emits one `blender-sync` event, and lets the session expire — not a persistent connection. Timeout is 60s (not 5s) to comfortably fit a heavy single object's export+transfer.
