# File Structure — 3d-art-plugin

Load when navigating `src/` or deciding where a new file belongs (placement rule: one `*_operators.py` + `*_sync.py` pair per sync concern — `CLAUDE.md`'s Conventions).

```
src/                             # the add-on's code only; ships whole in art3d_sync.zip as art3d_sync/
├── __init__.py                  # bl_info + register()/unregister()
├── constants.py                 # DEFAULT_SERVER_URL, PROTOCOL_VERSION, CLIENT_KIND, PLUGIN_VERSION (from bl_info), EXPORT_VERSION (part of every object key)
├── preferences.py               # AddonPreferences: show_header_button; server_url (shown with Developer Extras) — server_url(): env ART3D_SERVER_URL > preference > default
├── icons.py                     # the status dots (icons/dot_*.png) as preview icons: green ready, amber a step is needed, red a problem, blue sending, grey not connected
│
│   # UI — the N-panel tab "3D Art" (layout D "Channels"), the status-bar item, the 3D Viewport header button
├── panel.py                     # ART3D_PT_main_panel: status dot in the header; setup card or project row; Selected/All; one row per channel; Send All / progress + Cancel; report; Web Optimization
├── connection_ui.py             # state_dot() (dot + word for every surface), the setup card per missing step (account, approval, online access, server, update, project, browser), the project row + ART3D_MT_account, draw_status_card() for the popover
├── send_ui.py                   # Selected/All, the channel rows (summary, Send state, own button), running progress, after-send report (draw-call warning), the Web Optimization section (GPU hint, Resend Everything)
├── ui_text.py                   # wrap() (labels never wrap), note(), primary() (the one blue button), alert(), ring(), ago()/duration()/megabytes()
├── status_bar.py                # status-bar item: dot + "3D Art · <project>" with a popover (draw_status_card), or a running Send's progress bar + Cancel
├── view_header.py               # 3D Viewport header button: dot popover + Send All, or progress + Cancel; hidden by the preference
│
│   # Connection — device token, heartbeat, status
├── user_config.py               # the add-on's folder under the user config dir (<user config>/art3d) and atomic JSON writes there (0600)
├── credentials.py               # device tokens per server in <user config>/art3d/credentials.json; env ART3D_TOKEN is used instead, never written
├── api_client.py                # JSON over HTTP (urllib, certifi CA bundle) and request_bytes() for raw blobs; TransportError when there is no usable answer
├── pairing.py                   # RFC 8628 device-code flow: request_code(), poll_token() (pending / slow_down / denied / expired)
├── connection.py                # daemon worker thread, never bpy: pairing, heartbeat every 3 s (retries 1→2→5→10→30 s; carries a running Send's progress), project list, dev check; lock-guarded state + wake event; INSTANCE_ID per process; Session for other threads
├── runtime.py                   # main-thread side: 0.5 s timer + load_post/save_post/exit_pre handlers — hands the worker the scene context, sets status.current(), redraws on change (request_redraw() for a running Send), cancels a Send when another file opens, tells link_journal about loads and saves
├── status.py                    # status machine, first failing check wins: NOT_CONNECTED (WAITING_APPROVAL) → ONLINE_ACCESS_OFF → CONNECTING/OFFLINE → OUTDATED → NO_PROJECT → NO_BROWSER → READY; UI texts
├── account_operators.py         # Connect account, Cancel, Open browser again, Disconnect (revokes server-side), Dev: connect without browser (local DEV_TOOLS server), Open Preferences
├── project.py                   # the scene's binding: Scene properties art3d_project_id (raw field only with Developer Extras) + art3d_project_name (cached display name), bind(); record_binding() journals the project a Send goes to
├── project_picker.py            # Scene.art3d_project_pick: virtual dropdown over the account's projects (last fetch); get/set read and write the binding, nothing saved
├── project_operators.py         # Refresh Projects, New project (named after the .blend or the scene — default_name(), then bound), Open in browser
├── headless.py                  # bind_project(), wait_until(), wait_ready(), send() for `blender -b` scripts, where no timers run (recipe: CLAUDE.md)
│
│   # Send — the job, its network side, what it covers
├── send_job.py                  # SendJob: a Send as short main-thread steps from a timer (small channels, HDRI, then objects: key → missing? → bake + export → upload), pause outside Object Mode / off its scene, Cancel, per-channel rows + fraction (an unreadable HDRI fails only its own row), Report; can_send() poll; start(); blocking loop in background mode
├── send_operators.py            # Send All, Resend Everything, Cancel, and SendChannelBase (scope 'panel'|'selected'|'all', Shift+click = resend) every channel button builds on; Scene.art3d_scope
├── uploader.py                  # a Send's daemon thread, never bpy: /missing queries, raw /resource uploads (textures the browser lacks, then the glb), /sync messages in queue order, consecutive object entries batched; first error stops the Send
├── send_channels.py             # the small channels built from the job's own scene + selection (SendContext): render settings, sky, lights, cameras — a payload or the reason to skip
├── scene_graph.py               # plan(): which objects a Send covers (scope — Selected takes everything under the selection too —, Skip Hidden, hidden ancestors kept for hierarchy), stable ids, scene-wide deletions; entry_payload() (transform from matrix_local, `glb` = object key); summary() for the panel rows (Objects counts every entry, whatever its type)
├── object_key.py                # compute(): an object's glb key — hash of the evaluated mesh, geometry-nodes instances (sources + matrices), modifiers, materials + node trees + images, rig + action, settings, EXPORT_VERSION — plus triangles / draw calls / surface area; hash_tree() (also keys the HDRI)
├── export_cache.py              # this session's exports by object key (512 MB, least recently used out): a browser lacking a glb gets it again without a bake
├── mesh_memory.py               # float data of the modifier-evaluated meshes keyed this session: a mesh with the same topology + integer data and floats within 8 ULPs of a remembered one hashes those floats, so rounding (Bevel's UVs aren't bit-stable) keeps the key; copies share it, an undone edit finds its earlier one (256 MB, least recently used out)
├── web_settings.py              # Scene.art3d_web (Web Optimization): Max Texture, Bake Size / texel density, HDRI size, WebP/PNG, Meshopt/None, Skip Hidden; Snapshot (frozen per Send; signature() goes into object keys)
├── resource_pack.py             # GLTF_SEPARATE output → gzip glb whose images name their textures as art3d:<key> (data buffer moved to index 0 for meshopt), texture blobs keyed by content (content_key), image_size(), gpu_bytes()
│
│   # Export — one object → glb
├── gltf_exporter.py             # export_object() (Send path: capped textures, WebP/PNG, meshopt except animated, geometry-nodes instances as GPU instances, packed) and export_object_glb() (same pipeline as one lossless self-contained glb, for the fidelity suite); _prepared(): temp unparented/identity-transform duplicate in the scene collection, material preprocessing, cleanup
├── bake_device.py               # render_device(): Cycles on the GPU when Preferences has one enabled (else explicitly CPU); a failing GPU is given up for the session (is_device_error, give_up_gpu); gpu_hint() names an unused GPU
├── texture_cap.py               # cap_textures(): images above Max Texture swapped for scaled copies on per-slot material copies (node groups left alone)
├── material_flatten.py          # Surface that isn't one directly-wired Principled BSDF (e.g. Mix Shader) → one synthetic Principled
├── material_bake.py             # Cycles-bakes procedural Base Color/Roughness/Normal/Emission inputs to image textures (the exporter omits them otherwise; a Color Attribute × Image Texture base colour goes as COLOR_0); a bake that comes out flat ships as a factor; with the coat on (`_coat_bakes`) also Coat Weight/Roughness/Normal, the base bakes under shader_bake.coat_disabled()
├── material_coat.py             # coat post-pass on the exported glTF JSON (apply_coat_extras; inject_coat_extras on a GLB): extras.coat {ior?, tint?} and the clearcoatRoughnessFactor the exporter omits; owns inlined_principled() and has_coat(), which also gate material_bake's coat bakes
├── material_volume.py           # approximates Volume shaders (KHR_materials_volume nodes, or an alpha-blend fallback) — the exporter ignores the Volume socket
├── shader_bake.py               # shared bake plumbing: bake_size() (per-object resolution), new/tag/is_bake_image, flat_value() (a bake sampled where the faces land in UV space), find_principled_surface(), find_active_output(), emission-rewire socket bake, coat_disabled()
├── object_id.py                 # resolve_stable_ids(objects): batch-resolves `art3d_id` (custom property, survives renames) so a duplicate colliding with its original is decided deterministically (the holder this session knew under it, else by name); remembers each id by session_uid, so an undo that drops the property gets it back; get_existing_id(obj) is the side-effect-free lookup for the delete diff
├── sent_ids.py                  # ids included in the last successful object Send (Scene property art3d_sent_ids, also remembered for the session) — scene_graph.plan() diffs it to detect deletions
├── link_journal.py              # what the add-on wrote into the .blend since its last save (object ids, sent ids, the binding a Send used), mirrored to <user config>/art3d/links/<hash of the path>.json against that saved version (size + mtime): replayed by name when the same version is opened again, dropped on save or when the file changed on disk
│
│   # Channels — one *_operators.py (a SendChannelBase button) + *_sync.py (the payload) per concern
├── operators.py                 # ART3D_OT_send_scene — the Objects row
├── world_operators.py           # ART3D_OT_send_world — the Sky row
├── world_sync.py                # find_world_sky(): the Sky Texture the World really renders, walked from the active World Output's Surface as Cycles evaluates the tree (muted/invalid links dropped), plus its Background/Emission strength → sky payload (sunDisc only under Cycles)
├── world_hdri_operators.py      # ART3D_OT_send_world_hdri — the HDRI row
├── world_hdri_sync.py           # Material Preview's HDRI: the Environment Texture image re-encoded to Radiance HDR (at most the HDRI size, from a copy), or the Sky Texture baked to a 1K equirect; build_hdri_cached() skips an unchanged World; an image without pixels raises Unreadable ("Not found: <file>" / "Can't read: <file>"), hdri_problem() flags a missing file before a Send
├── light_operators.py           # ART3D_OT_send_lighting — the Lights row
├── light_sync.py                # Light objects → world-space position + unit direction (computed in Python), type/color/energyWatts/normalize/castShadow/shadowSoftSize/shadowFilterRadius/spot/area shape+size fields (color and power fold EEVEE's exposure and temperature tint; normalize is sent, not folded in); same stable id as scene_graph.py
├── render_settings_operators.py # ART3D_OT_send_render_settings — the Render row
├── render_settings_sync.py      # scene color management as the viewport display shader applies it (display device/emulation, view transform, look, exposure, gamma, white balance, curves, dither) + resolutionX/Y and pixelAspectX/Y (resolution and pixel aspect only give the synced camera's frame aspect)
├── curve_tables.py              # view_settings.curve_mapping → the per-channel tables Blender's GPU display shader reads (Combined curve premultiplied into R/G/B); render_settings_sync's `curves`
├── camera_operators.py          # ART3D_OT_send_camera — the Camera row
├── camera_sync.py               # Camera objects → optics only (lens, sensor size + fit, shift, clip, ortho scale, viewport display size); transform stays scene_graph.py's job
└── icons/                       # dot_{green,amber,red,blue,grey}.png (icons.py)
```

Shipped as `art3d_sync.zip` (gitignored, built locally) — rebuild/reinstall rule: `CLAUDE.md`'s Critical Discipline. Payload shapes and the editor↔server connection: [`../../docs/sync-protocol.md`](../../docs/sync-protocol.md).
