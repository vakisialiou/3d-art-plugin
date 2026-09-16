# File Structure — 3d-art-plugin

Read this on demand when navigating this repo's codebase or deciding where a new file belongs.

---

```
art3d_sync/                     # addon package — name must be a valid Python
│                                # identifier (no hyphens, no leading digit),
│                                # since Blender imports it as a module
├── __init__.py                 # bl_info + register()/unregister()
├── panel.py                    # N-panel UI, sectioned: General Settings / Objects / Lighting
├── constants.py                 # SERVER_URL, shared by all operator modules
├── operators.py                # ART3D_OT_send_scene (scope: 'selected'|'all') — orchestrates, emits
├── world_operators.py          # ART3D_OT_send_world — orchestrates, emits "blender-world-sync"
├── world_sync.py               # Reads the active World's Sky Texture node → plain-dict sky payload
├── light_operators.py          # ART3D_OT_send_lighting (scope: 'selected'|'all') — orchestrates, emits "blender-lighting-sync"
├── light_sync.py               # Walks Light objects → plain-dict payload, world-space (not part of the object hierarchy)
├── render_settings_operators.py # ART3D_OT_send_render_settings — orchestrates, emits "blender-render-settings-sync"
├── render_settings_sync.py     # Reads scene.view_settings (exposure/view transform/look) → plain-dict payload
├── scene_graph.py              # Walks selection/scene → objects[] payload entries (id, parentId, transform, real obj.type)
├── gltf_exporter.py            # One object → .glb bytes, via a temp unparented/identity-transform duplicate
└── socket_client.py            # stdlib-only Engine.IO/Socket.IO polling client

blender/                        # Small demo scenes/assets used to test and demonstrate sync — not addon source
```

Ships zipped as `art3d_sync.zip`, installed via Blender's Preferences → Add-ons → Install from Disk (rebuild/reinstall discipline and the actual command: `CLAUDE.md`'s Critical Discipline). No pip install required — `socket_client.py` speaks the Engine.IO/Socket.IO v4 polling protocol directly over `urllib`, since Blender's bundled Python has no `python-socketio`/`websocket-client`. Each button press opens a short-lived polling session, connects, emits one `blender-sync` event, and lets the session expire — not a persistent connection. Timeout is 60s (not 5s) to comfortably fit a heavy single object's export+transfer.
