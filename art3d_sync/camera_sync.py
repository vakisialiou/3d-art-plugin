"""Camera objects → optics-only payload, keyed by the same stable id as
scene_graph.py. Never send position/rotation here: the transform belongs to
scene_graph.py's channel, and duplicating it lets the two drift apart.
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
                "clipNearM": camera.clip_start,
                "clipFarM": camera.clip_end,
                # PANO has no three.js equivalent — sent as PERSP.
                "isOrtho": camera.type == "ORTHO",
                "orthoScaleM": camera.ortho_scale,
            }
        )
    return payload
