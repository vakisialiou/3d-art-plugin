"""Reads the active World's Sky Texture node (Nishita / multiple-scattering —
Blender's physically-based procedural sky) into a plain-dict payload. Mirrors
scene_graph.py's approach: gather into plain data here, let the browser side
decide how to apply it.
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
        # Real Nishita/multiple-scattering inputs (sky_node.sky_type for this
        # node is "MULTIPLE_SCATTERING" — confirmed by introspecting the live
        # node, not assumed). "turbidity" is a property that exists on this
        # node class but Blender only actually uses it for the PREETHAM/
        # HOSEK_WILKIE sky_type — it plays no role in MULTIPLE_SCATTERING's
        # own computation, so it's deliberately not sent; these fields below
        # are the ones Blender's Nishita model actually reads.
        "sunSizeRad": sky_node.sun_size,
        "sunIntensity": sky_node.sun_intensity,
        "airDensity": sky_node.air_density,
        "aerosolDensity": sky_node.aerosol_density,
        "ozoneDensity": sky_node.ozone_density,
        "altitudeM": sky_node.altitude,
        # "groundAlbedo" (sky_node.ground_albedo) is deliberately NOT sent —
        # confirmed by reading Blender's own MULTIPLE_SCATTERING sky_type C++
        # source that this field is hardcoded to 0.3 there too, the node's
        # own UI slider does nothing for this sky_type even in Blender
        # itself. Not a browser-side limitation to work around — there is
        # nothing real to sync. See CLAUDE.md's "Settings Display Model".
        "strength": strength,
    }
