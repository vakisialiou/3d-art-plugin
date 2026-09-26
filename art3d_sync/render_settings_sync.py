"""Reads scene-level render/color-management settings into a plain-dict
payload. Only fields this app's own browser-side engine actually applies and
that actually affect the rendered result belong here — see CLAUDE.md's
"Settings Display Model": the plugin should never send a field just because
Blender has it. `viewTransform` rides alongside `exposure` now that the
browser side has a real AgX port (ported from Blender's own OCIO config, the
same way the Nishita sky was) — sent verbatim, since Blender's own enum is
much larger than what the browser implements ('Standard'/'AgX' only; any
other value falls back to 'Standard' on arrival, a disclosed simplification).
`look`/`engine` still aren't sent — no Look-curve/engine concept exists on
the browser side to apply them to.

`resolutionX`/`resolutionY` (`scene.render.resolution_x/_y`) are the one
exception to "only what affects the rendered *pixels*" — the browser side
doesn't render at this resolution (its own canvas is whatever size the
viewport is), but "Camera view" needs Blender's real output aspect ratio to
compute the synced camera's vertical FOV correctly (see render.worker.ts's
computeBlenderCameraPose) — without it, that FOV was derived from the live
browser viewport's own aspect instead, showing more or less of the scene
above/below the frame than Blender's actual render does at the same camera.
"""

import bpy


def build_render_settings_sync(context: bpy.types.Context) -> dict:
    return {
        "exposure": context.scene.view_settings.exposure,
        "viewTransform": context.scene.view_settings.view_transform,
        "resolutionX": context.scene.render.resolution_x,
        "resolutionY": context.scene.render.resolution_y,
    }
