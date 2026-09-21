"""Walks Light objects into a plain-dict payload. Mirrors scene_graph.py's
approach (gather into plain data here, let the browser side decide how to
apply it) but lights are a separate sync channel, not part of the object/
hierarchy sync — position/direction travel in world space, not local-to-parent.
"""

from mathutils import Vector

import bpy

from .object_id import get_stable_id

# Blender lights point down their local -Z axis — sending a precomputed
# world-space unit direction means the browser never has to redo this
# quaternion math itself.
_LOCAL_FORWARD = Vector((0.0, 0.0, -1.0))


def collect_selected_lights(context: bpy.types.Context) -> list:
    return [obj for obj in context.selected_objects if obj.type == "LIGHT"]


def collect_all_scene_lights(context: bpy.types.Context) -> list:
    return [obj for obj in context.scene.objects if obj.type == "LIGHT"]


def build_light_sync(objects: list) -> list:
    payload = []
    for obj in objects:
        light = obj.data
        world_position = obj.matrix_world.translation
        direction = (obj.matrix_world.to_quaternion() @ _LOCAL_FORWARD).normalized()

        entry = {
            # Same stable id as the object/hierarchy sync (scene_graph.py) —
            # this is the same Blender object, just walked by a second channel.
            "id": get_stable_id(obj),
            "type": light.type,  # 'POINT' | 'SUN' | 'SPOT' | 'AREA'
            "color": [light.color.r, light.color.g, light.color.b],
            # Radiometric Watts (Blender) — the browser applies its own
            # visually-tuned coefficient, not a physical lm/W conversion.
            "energyWatts": light.energy,
            "position": [world_position.x, world_position.y, world_position.z],
            "direction": [direction.x, direction.y, direction.z],
            "castShadow": light.use_shadow,
            # Blender's actual shadow-softness control — a real light *size*
            # (radius, in meters) for POINT/SPOT/AREA, an angular diameter
            # (radians) for SUN. Both drive how soft/blurry Blender's own
            # shadows are; sent as one field so the browser has a genuine
            # per-light softness value to work from instead of a flat guess.
            "shadowSoftSize": light.angle if light.type == "SUN" else light.shadow_soft_size,
            "spotAngleRad": light.spot_size if light.type == "SPOT" else None,
            "spotBlend": light.spot_blend if light.type == "SPOT" else None,
            "areaWidth": light.size if light.type == "AREA" else None,
            "areaHeight": (light.size_y if light.shape in ("RECTANGLE", "ELLIPSE") else light.size)
            if light.type == "AREA"
            else None,
        }
        payload.append(entry)

    return payload
