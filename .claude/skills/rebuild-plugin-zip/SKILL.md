---
name: rebuild-plugin-zip
description: Rebuild and reinstall art3d_sync.zip after changing anything under art3d_sync/ in 3d-art-plugin. Use whenever you edit a .py file in that folder, before telling the user the change is ready to test.
---

# Rebuild `art3d_sync.zip`

Blender loads the addon from the installed zip, not from this source tree — a source edit alone does nothing until rebuilt and reinstalled.

1. Rebuild the zip from repo root:
   ```bash
   rm -f art3d_sync.zip && zip -r art3d_sync.zip art3d_sync -x "*.pyc" -x "__pycache__/*"
   ```
2. Tell the user to reinstall it: Blender Preferences → Add-ons → Install from Disk → select the new `art3d_sync.zip`.
3. Tell the user to **restart Blender** after reinstalling — never trust a hot-reinstall. An already-running session can have old modules cached in `sys.modules`, so a stale copy stays active and silently reintroduces bugs that look like regressions.

Do this immediately after the source change, not batched with other work — a forgotten rebuild is the most common cause of "my fix didn't work" here.
