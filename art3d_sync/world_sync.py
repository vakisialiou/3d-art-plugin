"""Active World's Sky Texture node (Nishita / MULTIPLE_SCATTERING) → plain-dict
payload.
"""

import math

import bpy

_SKY_NODE_TYPE = "ShaderNodeTexSky"
_BACKGROUND_NODE_TYPE = "ShaderNodeBackground"


def build_world_sync(context: bpy.types.Context) -> dict | None:
    world = context.scene.world
    if world is None or world.node_tree is None:
        return None

    sky_node = next(
        (node for node in world.node_tree.nodes if node.bl_idname == _SKY_NODE_TYPE),
        None,
    )
    if sky_node is None:
        return None

    background_node = next(
        (node for node in world.node_tree.nodes if node.bl_idname == _BACKGROUND_NODE_TYPE),
        None,
    )
    strength = background_node.inputs["Strength"].default_value if background_node else 1.0

    return {
        "sunElevationDeg": math.degrees(sky_node.sun_elevation),
        "sunRotationDeg": math.degrees(sky_node.sun_rotation),
        # The inputs MULTIPLE_SCATTERING actually reads. `turbidity` is
        # PREETHAM/HOSEK_WILKIE-only, so it isn't sent.
        "sunSizeRad": sky_node.sun_size,
        "sunIntensity": sky_node.sun_intensity,
        "airDensity": sky_node.air_density,
        "aerosolDensity": sky_node.aerosol_density,
        "ozoneDensity": sky_node.ozone_density,
        "altitudeM": sky_node.altitude,
        # `ground_albedo` isn't sent: Blender's MULTIPLE_SCATTERING source
        # hardcodes it to 0.3, so the node's slider has no effect.
        "strength": strength,
    }
