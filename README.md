# 3d-art-plugin

Blender addon that exports objects as glTF (one small `.glb` per object) and
sends them to `3d-art-api` over Socket.IO, for live preview in `3d-art-web` —
geometry, materials, and textures included, with object hierarchy resolved by
id/parentId on the browser side. See the architecture doc in the `3d-art`
repo for the full sync strategy and why it's per-object rather than a
whole-scene blob (short version: a single 4k PBR material blew a whole-scene
export up to 90MB and broke the transport).

Built for Blender 5.2.1. Uses only the Python standard library (`urllib`) —
no pip install needed inside Blender.

## Install

1. `art3d_sync.zip` in this folder is the packaged addon (rebuild it with
   `zip -r art3d_sync.zip art3d_sync` if you change the source).
2. In Blender: Edit → Preferences → Add-ons → Install from Disk… → select
   `art3d_sync.zip` → enable the "3D Art Sync" checkbox. **After updating the
   zip, fully restart Blender** — an already-running session can keep the old
   Python modules cached even after the files on disk change.
3. In the 3D Viewport, open the sidebar (press `N`) → "3D Art" tab → click
   **Send Selected** (selection + its ancestors) or **Send All** (whole scene).

## Configuration

The API URL is hardcoded in `art3d_sync/operators.py` as `SERVER_URL`
(default `http://localhost:3000`, matching `3d-art-api`'s default port).
