"""Light objects → plain-dict payload for the separate lighting channel.
The world-space position/direction are only a fallback placement: the browser
takes the light's transform from scene_graph.py's entry once it arrives.

Color and energy are the effective values EEVEE renders with
(eevee_light.cc's Light::sync): exposure, temperature and an unnormalized
light's area are folded in, so the browser needs none of those fields.

Audited and not sent, because EEVEE never reads them or the browser can't
apply them: spread (EEVEE ignores it), shadow_buffer_clip_start (EEVEE reads
it only for light probes), shadow_maximum_resolution/use_absolute_resolution
(virtual shadow map LOD), use_shadow_jitter/shadow_jitter_overblur (off in
the viewport), diffuse/specular/transmission/volume factors,
use_custom_distance/cutoff_distance, use_nodes.
"""

from mathutils import Vector

import bpy

from .object_id import resolve_stable_ids

# Blender lights point down their local -Z axis.
_LOCAL_FORWARD = Vector((0.0, 0.0, -1.0))

# EEVEE's to_light_type(): DISK/ELLIPSE trace an ellipse, SQUARE/RECTANGLE a rectangle.
_ELLIPSE_SHAPES = ("DISK", "ELLIPSE")


def collect_selected_lights(context: bpy.types.Context) -> list:
    return [obj for obj in context.selected_objects if obj.type == "LIGHT"]


def collect_all_scene_lights(context: bpy.types.Context) -> list:
    return [obj for obj in context.scene.objects if obj.type == "LIGHT"]


def _effective_color(light: bpy.types.Light) -> list:
    """BKE_light_color(): the color times the blackbody tint when use_temperature is on."""
    color = [light.color.r, light.color.g, light.color.b]
    if light.use_temperature:
        tint = light.temperature_color
        color = [color[0] * tint[0], color[1] * tint[1], color[2] * tint[2]]
    return color


def _effective_power(obj: bpy.types.Object) -> float:
    """BKE_light_power() (energy * 2^exposure), times BKE_light_area() for an unnormalized light."""
    light = obj.data
    power = light.energy * 2.0**light.exposure
    if not light.normalize:
        power *= light.area(matrix_world=obj.matrix_world)
    return power


def build_light_sync(objects: list) -> list:
    resolved_ids = resolve_stable_ids(objects)
    payload = []
    for obj in objects:
        light = obj.data
        world_position = obj.matrix_world.translation
        direction = (obj.matrix_world.to_quaternion() @ _LOCAL_FORWARD).normalized()
        is_area = light.type == "AREA"

        entry = {
            # Same stable id as scene_graph.py's entry for this object.
            "id": resolved_ids[obj.name],
            "type": light.type,  # 'POINT' | 'SUN' | 'SPOT' | 'AREA'
            "color": _effective_color(light),
            # Radiometric Watts; the browser applies its own tuned coefficient,
            # not a physical lm/W conversion.
            "energyWatts": _effective_power(obj),
            "position": [world_position.x, world_position.y, world_position.z],
            "direction": [direction.x, direction.y, direction.z],
            "castShadow": light.use_shadow,
            # Radius in meters for POINT/SPOT, angular diameter in radians for
            # SUN. EEVEE's AREA branch never reads it.
            "shadowSoftSize": None if is_area else (light.angle if light.type == "SUN" else light.shadow_soft_size),
            "shadowFilterRadius": light.shadow_filter_radius,
            "spotAngleRad": light.spot_size if light.type == "SPOT" else None,
            "spotBlend": light.spot_blend if light.type == "SPOT" else None,
            "areaShape": ("ELLIPSE" if light.shape in _ELLIPSE_SHAPES else "RECT") if is_area else None,
            "areaWidth": light.size if is_area else None,
            "areaHeight": (light.size_y if light.shape in ("RECTANGLE", "ELLIPSE") else light.size)
            if is_area
            else None,
        }
        payload.append(entry)

    return payload
