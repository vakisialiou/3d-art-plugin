---
name: rebuild-plugin-zip
description: Rebuild and reinstall skyray.zip after changing anything under src/ in skyray-plugin. Use whenever you edit a .py file in that folder, before telling the user the change is ready to test.
---

# Rebuild `skyray.zip`

Blender runs the installed zip, not this source tree — a source edit does nothing until rebuilt and reinstalled.

1. From the `skyray-plugin` repo root (the whole `src/` goes into the zip as `skyray/`, the add-on's module name):
   ```bash
   python3 - <<'EOF'
   import pathlib, zipfile
   src = pathlib.Path("src")
   with zipfile.ZipFile("skyray.zip", "w", zipfile.ZIP_DEFLATED) as archive:
       for path in [src, *sorted(src.rglob("*"))]:
           if "__pycache__" not in path.parts:
               archive.write(path, "skyray" / path.relative_to(src))
   EOF
   ```
2. Tell the user to reinstall: Blender Preferences → Add-ons → Install from Disk → the new `skyray.zip`.
3. Tell the user to **restart Blender** — never trust a hot-reinstall: a running session keeps old modules in `sys.modules`, so the stale copy stays active and its bugs look like regressions.

Do this immediately after the source change, not batched with other work — a forgotten rebuild is the usual cause of "my fix didn't work".
