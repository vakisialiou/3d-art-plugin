"""Walks Camera objects into a plain-dict payload. Mirrors light_sync.py's
approach — optics only, keyed by the same stable id as the object/hierarchy
sync (scene_graph.py), which already carries this same object's transform.
Never resend position/rotation here — see TODO-sync-redesign.md P1.3 for why
that duplication was a real bug for lights, and CLAUDE.md's Settings Display
Model for "the plugin only sends fields the browser side can actually apply".
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
                # PANO has no three.js equivalent — treated as PERSP, same
                # "closest real analog" call the sync-review card title already
                # makes elsewhere rather than adding a third, unsupported mode.
                "isOrtho": camera.type == "ORTHO",
                "orthoScaleM": camera.ortho_scale,
            }
        )
    return payload
