"""Scene color management + render size → plain-dict payload.

Everything Blender's viewport display shader applies, from one audit of
ColorManagedDisplaySettings / ColorManagedViewSettings: display device and
emulation, view transform and look (full OCIO names, verbatim), exposure
(stops), gamma, white balance and RGB curves (None while their toggles are
off), and render.dither_intensity. Not sent: curve_mapping.tone (the GPU path
ignores FILMLIKE), use_clip (only the curve tables matter),
white_balance_whitepoint (derived from temperature/tint), is_hdr and
support_emulation (read-only, derived from the display).

The browser never renders at `resolutionX`/`resolutionY`; they only give the
synced camera Blender's output aspect for its vertical FOV (camera-rig.ts's
computeBlenderCameraPose).
"""

import bpy

from .curve_tables import build_curve_tables


def _white_balance(view: bpy.types.ColorManagedViewSettings) -> dict | None:
    if not view.use_white_balance:
        return None
    return {
        "temperature": view.white_balance_temperature,
        "tint": view.white_balance_tint,
    }


def build_render_settings_sync(context: bpy.types.Context) -> dict:
    scene = context.scene
    view = scene.view_settings
    return {
        "displayDevice": scene.display_settings.display_device,
        "emulation": scene.display_settings.emulation,
        "viewTransform": view.view_transform,
        "look": view.look,
        "exposure": view.exposure,
        "gamma": view.gamma,
        "whiteBalance": _white_balance(view),
        "curves": build_curve_tables(view.curve_mapping) if view.use_curve_mapping else None,
        "dither": scene.render.dither_intensity,
        "resolutionX": scene.render.resolution_x,
        "resolutionY": scene.render.resolution_y,
    }
