"""Scene render/color-management settings → plain-dict payload.

`viewTransform` is sent verbatim; the browser implements only 'Standard' and
'AgX' and falls back to 'Standard' for anything else. `look`/`engine` aren't
sent — the browser has nothing to apply them to.

The browser never renders at `resolutionX`/`resolutionY`; with the pixel
aspect they only give the synced camera Blender's frame aspect,
(resolution_x * pixel_aspect_x) / (resolution_y * pixel_aspect_y), as in
BKE_camera_params_compute_viewplane (camera-rig.ts's computeBlenderCameraPose).
`resolution_percentage` and border/crop don't change that aspect and aren't
sent.
"""

import bpy


def build_render_settings_sync(context: bpy.types.Context) -> dict:
    return {
        "exposure": context.scene.view_settings.exposure,
        "viewTransform": context.scene.view_settings.view_transform,
        "resolutionX": context.scene.render.resolution_x,
        "resolutionY": context.scene.render.resolution_y,
        "pixelAspectX": context.scene.render.pixel_aspect_x,
        "pixelAspectY": context.scene.render.pixel_aspect_y,
    }
