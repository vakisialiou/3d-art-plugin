"""Camera objects → optics-only payload, keyed by the same stable id as
scene_graph.py. Never send position/rotation here: the transform belongs to
scene_graph.py's channel, and duplicating it lets the two drift apart.

Sent: every input of Blender's camera frame (BKE_camera_params_compute_viewplane
— lens, sensor size + fit, shift, ortho scale, clip range) plus `display_size`
for the viewport icon. Not sent, because the browser has nothing to apply them
to: `angle*` (derived from lens + sensor), `lens_unit` (UI only), `dof.*` (no
depth of field), `stereo.*` (no stereo), passepartout, safe areas, composition
guides, `show_*` and background images (no Camera view overlays), and the
PANO/CUSTOM lens settings (those types are sent as PERSP).
"""

import bpy

from .object_id import resolve_stable_ids


def collect_selected_cameras(context: bpy.types.Context) -> list:
    return [obj for obj in context.selected_objects if obj.type == "CAMERA"]


def collect_all_scene_cameras(context: bpy.types.Context) -> list:
    return [obj for obj in context.scene.objects if obj.type == "CAMERA"]


def build_camera_sync(objects: list) -> list:
    resolved_ids = resolve_stable_ids(objects)
    payload = []
    for obj in objects:
        camera = obj.data
        payload.append(
            {
                "id": resolved_ids[obj.name],
                "lensMm": camera.lens,
                "sensorWidthMm": camera.sensor_width,
                "sensorHeightMm": camera.sensor_height,
                # 'AUTO' | 'HORIZONTAL' | 'VERTICAL', verbatim.
                "sensorFit": camera.sensor_fit,
                # Fractions of the fitted frame dimension, as Blender stores them.
                "shiftX": camera.shift_x,
                "shiftY": camera.shift_y,
                "clipNearM": camera.clip_start,
                "clipFarM": camera.clip_end,
                # PANO has no three.js equivalent — sent as PERSP.
                "isOrtho": camera.type == "ORTHO",
                "orthoScaleM": camera.ortho_scale,
                "displaySizeM": camera.display_size,
            }
        )
    return payload
