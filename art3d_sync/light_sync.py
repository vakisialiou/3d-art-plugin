"""Light objects → plain-dict payload for the separate lighting channel.
The world-space position/direction are only a fallback placement: the browser
takes the light's transform from scene_graph.py's entry once it arrives.
"""

from mathutils import Vector

import bpy

from .object_id import resolve_stable_ids

# Blender lights point down their local -Z axis.
_LOCAL_FORWARD = Vector((0.0, 0.0, -1.0))


def collect_selected_lights(context: bpy.types.Context) -> list:
    return [obj for obj in context.selected_objects if obj.type == "LIGHT"]


def collect_all_scene_lights(context: bpy.types.Context) -> list:
    return [obj for obj in context.scene.objects if obj.type == "LIGHT"]


def build_light_sync(objects: list) -> list:
    resolved_ids = resolve_stable_ids(objects)
    payload = []
    for obj in objects:
        light = obj.data
        world_position = obj.matrix_world.translation
        direction = (obj.matrix_world.to_quaternion() @ _LOCAL_FORWARD).normalized()

        entry = {
            # Same stable id as scene_graph.py's entry for this object.
            "id": resolved_ids[obj.name],
            "type": light.type,  # 'POINT' | 'SUN' | 'SPOT' | 'AREA'
            "color": [light.color.r, light.color.g, light.color.b],
            # Radiometric Watts; the browser applies its own tuned coefficient,
            # not a physical lm/W conversion.
            "energyWatts": light.energy,
            "position": [world_position.x, world_position.y, world_position.z],
            "direction": [direction.x, direction.y, direction.z],
            "castShadow": light.use_shadow,
            # Radius in meters for POINT/SPOT/AREA, angular diameter in
            # radians for SUN — Blender's shadow-softness control either way.
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
