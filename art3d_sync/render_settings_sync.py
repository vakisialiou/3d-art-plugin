"""Scene render/color-management settings → plain-dict payload.

`viewTransform` is sent verbatim; the browser implements only 'Standard' and
'AgX' and falls back to 'Standard' for anything else. `look`/`engine` aren't
sent — the browser has nothing to apply them to.

The browser never renders at `resolutionX`/`resolutionY`; they only give the
synced camera Blender's output aspect for its vertical FOV (camera-rig.ts's
computeBlenderCameraPose).
"""

import bpy


def build_render_settings_sync(context: bpy.types.Context) -> dict:
    return {
        "exposure": context.scene.view_settings.exposure,
        "viewTransform": context.scene.view_settings.view_transform,
        "resolutionX": context.scene.render.resolution_x,
        "resolutionY": context.scene.render.resolution_y,
    }
