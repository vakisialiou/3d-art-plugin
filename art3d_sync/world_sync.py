"""Active World's Sky Texture node (Nishita: Single or Multiple Scattering) →
plain-dict payload.

find_world_sky() walks from the active World Output: Surface → Background →
Color → Sky Texture, so a disconnected or second Sky node isn't picked. Any
other graph falls back to the first Sky/Background node by type.
"""

import math

import bpy

_OUTPUT_NODE_TYPE = "ShaderNodeOutputWorld"
_SKY_NODE_TYPE = "ShaderNodeTexSky"
_BACKGROUND_NODE_TYPE = "ShaderNodeBackground"

# The two Nishita models the browser renders. PREETHAM/HOSEK_WILKIE (Blender's
# "Legacy" types) are different analytic models and aren't sent.
SUPPORTED_SKY_TYPES = {"SINGLE_SCATTERING", "MULTIPLE_SCATTERING"}


def _linked_node(node: bpy.types.Node, input_name: str, bl_idname: str) -> bpy.types.Node | None:
    socket = node.inputs.get(input_name)
    if socket is None or not socket.is_linked:
        return None
    linked = socket.links[0].from_node
    return linked if linked.bl_idname == bl_idname else None


def _find_output(world: bpy.types.World) -> bpy.types.Node | None:
    output = None
    for node in world.node_tree.nodes:
        if node.bl_idname == _OUTPUT_NODE_TYPE:
            if node.is_active_output:
                return node
            if output is None:
                output = node
    return output


def _first_by_type(world: bpy.types.World, bl_idname: str) -> bpy.types.Node | None:
    return next((node for node in world.node_tree.nodes if node.bl_idname == bl_idname), None)


def find_world_sky(
    world: bpy.types.World | None,
) -> tuple[bpy.types.ShaderNodeTexSky, bpy.types.ShaderNodeBackground | None] | None:
    """(sky, background), background None if there's none (Strength then
    counts as 1). None if the World has no Sky Texture node."""
    if world is None or world.node_tree is None:
        return None

    output = _find_output(world)
    background = _linked_node(output, "Surface", _BACKGROUND_NODE_TYPE) if output else None
    sky = _linked_node(background, "Color", _SKY_NODE_TYPE) if background else None
    if sky is not None:
        return sky, background

    sky = _first_by_type(world, _SKY_NODE_TYPE)
    if sky is None:
        return None
    return sky, _first_by_type(world, _BACKGROUND_NODE_TYPE)


def build_world_sync(
    sky: bpy.types.ShaderNodeTexSky, background: bpy.types.ShaderNodeBackground | None
) -> dict:
    """Every input the Nishita models read, for a SUPPORTED_SKY_TYPES sky.
    Not sent: `turbidity`, `ground_albedo` and `sun_direction`
    (PREETHAM/HOSEK_WILKIE only), `texture_mapping` (legacy, not in the UI),
    `color_mapping` (never applied to a sky) and a linked Vector input
    (unavailable with the sun disc on; node graphs can't be applied)."""
    strength = background.inputs["Strength"].default_value if background else 1.0

    return {
        "skyType": sky.sky_type,
        "sunDisc": sky.sun_disc,
        # Unwrapped, as stored: the browser applies Blender's own wrap.
        "sunElevationDeg": math.degrees(sky.sun_elevation),
        "sunRotationDeg": math.degrees(sky.sun_rotation),
        "sunSizeRad": sky.sun_size,
        "sunIntensity": sky.sun_intensity,
        "airDensity": sky.air_density,
        "aerosolDensity": sky.aerosol_density,
        "ozoneDensity": sky.ozone_density,
        "altitudeM": sky.altitude,
        "strength": strength,
    }
