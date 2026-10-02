---
name: rebuild-plugin-zip
description: Rebuild and reinstall art3d_sync.zip after changing anything under art3d_sync/ in 3d-art-plugin. Use whenever you edit a .py file in that folder, before telling the user the change is ready to test.
---

# Rebuild `art3d_sync.zip`

Blender runs the installed zip, not this source tree — a source edit does nothing until rebuilt and reinstalled.

1. From the `3d-art-plugin` repo root:
   ```bash
   rm -f art3d_sync.zip && zip -r art3d_sync.zip art3d_sync -x "*.pyc" -x "__pycache__/*"
   ```
2. Tell the user to reinstall: Blender Preferences → Add-ons → Install from Disk → the new `art3d_sync.zip`.
3. Tell the user to **restart Blender** — never trust a hot-reinstall: a running session keeps old modules in `sys.modules`, so the stale copy stays active and its bugs look like regressions.

Do this immediately after the source change, not batched with other work — a forgotten rebuild is the usual cause of "my fix didn't work".
