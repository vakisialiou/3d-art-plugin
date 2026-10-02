"""Approximates Volume shaders (Volume Scatter / Absorption / Principled
Volume) for glTF, which has no volume model; Blender's glTF exporter reads
only the Surface socket (io_scene_gltf2 exp/material/pbr_metallic_roughness.py).

Two cases, detected generically:

1. Surface is a Principled with real Transmission Weight: the exporter already
   writes KHR_materials_transmission from it, so its transmission is left as-is.
   The Volume's Color/Density is added as KHR_materials_volume through what
   export_volume (exp/material/extensions/volume.py) reads: a disconnected
   "glTF Material Output" group carrying Thickness, plus a Volume Absorption
   node on the output's Volume input carrying Color/Density.
   three.js's GLTFLoader maps both extensions onto MeshPhysicalMaterial, so no
   web-side code is needed.
2. No transmissive Surface ("pure fog"): a flat alpha-blend shell, alpha =
   1 - exp(-density * thickness) (Beer-Lambert).

thickness is always the object's largest bounding dimension. KHR_materials_volume
mapping:
- thicknessFactor = thickness. A procedural Density has no spatial slot except
  thicknessTexture, so its raw baked map goes there to keep the variation.
- attenuationDistance = 1 / Density, computed by export_volume from the
  Absorption node — a procedural Density contributes its baked mean.
- attenuationColor = the volume node's Color (mean if baked: no texture slot).
- Principled Volume's Absorption Color and Anisotropy aren't mapped (no
  verified gain / no glTF equivalent); its Emission goes onto the Surface
  Principled's Emission inputs.
"""

import math
from array import array
from typing import Optional

import bpy

from .shader_bake import bake_socket_to_image_node, find_output, find_principled_surface

_VOLUME_NODE_TYPES = {
    "ShaderNodeVolumeScatter",
    "ShaderNodeVolumeAbsorption",
    "ShaderNodeVolumePrincipled",
}

_BAKE_IMAGE_PREFIX = "__art3d_volume"

# At or below this, Transmission Weight counts as none → alpha-blend fallback.
_TRANSMISSION_EPSILON = 0.001

# io_scene_gltf2's get_gltf_node_name() (com/material_helpers.py); the
# exporter finds the group by this node_tree name prefix, case-insensitively.
_GLTF_SETTINGS_GROUP_NAME = "glTF Material Output"


def find_volume_node(material: Optional[bpy.types.Material]):
    if material is None or not material.use_nodes or material.node_tree is None:
        return None
    output = find_output(material)
    if output is None:
        return None
    volume_input = output.inputs.get("Volume")
    if volume_input is None or not volume_input.is_linked:
        return None
    from_node = volume_input.links[0].from_node
    if from_node.bl_idname not in _VOLUME_NODE_TYPES:
        return None
    return from_node


def is_volume_material(material: Optional[bpy.types.Material]) -> bool:
    return find_volume_node(material) is not None


def _has_real_transmission(material: bpy.types.Material) -> bool:
    surface = find_principled_surface(material)
    if surface is None:
        return False
    transmission = surface.inputs.get("Transmission Weight")
    if transmission is None:
        return False
    if transmission.is_linked:
        return True
    return transmission.default_value > _TRANSMISSION_EPSILON


def _resolve_channel(material: bpy.types.Material, socket, image_name: str, colorspace: str):
    """('factor', default_value) for an unlinked socket, else ('image', node):
    a directly linked Image Texture node is reused, anything else is baked."""
    if socket is None:
        return 'factor', None
    if not socket.is_linked:
        value = socket.default_value
        return 'factor', tuple(value) if hasattr(value, '__len__') else value
    from_node = socket.links[0].from_node
    if from_node.bl_idname == "ShaderNodeTexImage":
        return 'image', from_node
    return 'image', bake_socket_to_image_node(material, socket.links[0].from_socket, image_name, colorspace)


def _apply_channel(tree: bpy.types.NodeTree, target_socket, kind: str, value) -> None:
    if kind == 'factor':
        if value is not None:
            target_socket.default_value = value
        return
    tree.links.new(value.outputs["Color"], target_socket)


def _image_mean_channel(image: bpy.types.Image, channel: int = 0) -> float:
    count = len(image.pixels)
    buffer = array('f', bytes(4 * count))
    image.pixels.foreach_get(buffer)
    total = 0.0
    n = 0
    for i in range(channel, count, 4):
        total += buffer[i]
        n += 1
    return total / n if n else 0.0


def _get_or_create_gltf_settings_group() -> bpy.types.NodeTree:
    """Mirrors io_scene_gltf2's create_settings_group() (com/material_helpers.py).
    The otherwise-unused Occlusion socket is required: materials.py's
    __can_use_inline() checks only for it, and the inline path it guards
    drops every disconnected node — silently losing KHR_materials_volume."""
    existing = bpy.data.node_groups.get(_GLTF_SETTINGS_GROUP_NAME)
    if existing is not None:
        return existing
    group = bpy.data.node_groups.new(_GLTF_SETTINGS_GROUP_NAME, "ShaderNodeTree")
    group.interface.new_socket("Occlusion", socket_type="NodeSocketFloat")
    thickness = group.interface.new_socket("Thickness", socket_type="NodeSocketFloat")
    thickness.default_value = 0.0
    group.nodes.new("NodeGroupOutput")
    group_input = group.nodes.new("NodeGroupInput")
    group_input.location = -200, 0
    return group


def _add_volume_extension_nodes(material: bpy.types.Material, thickness: float, image_prefix: str) -> None:
    """Module docstring, case 1: adds the node pair export_volume reads."""
    tree = material.node_tree
    output = find_output(material)
    vol_node = find_volume_node(material)

    settings_node = tree.nodes.new("ShaderNodeGroup")
    settings_node.node_tree = _get_or_create_gltf_settings_group()

    density_socket = vol_node.inputs.get("Density")
    density_kind, density_value = _resolve_channel(
        material, density_socket, f"{image_prefix}_density", "Non-Color",
    )

    absorption = tree.nodes.new("ShaderNodeVolumeAbsorption")
    if density_kind == 'image':
        # thicknessTexture is 0..1 times thicknessFactor, which the exporter
        # reads from a constant multiply on the texture (get_factor_from_socket,
        # else 1.0) — so scale by the object's size explicitly.
        scale = tree.nodes.new("ShaderNodeMath")
        scale.operation = 'MULTIPLY'
        scale.inputs[1].default_value = thickness
        tree.links.new(density_value.outputs["Color"], scale.inputs[0])
        tree.links.new(scale.outputs["Value"], settings_node.inputs["Thickness"])
        absorption.inputs["Density"].default_value = _image_mean_channel(density_value.image)
    else:
        settings_node.inputs["Thickness"].default_value = thickness
        if density_value is not None:
            absorption.inputs["Density"].default_value = max(density_value, 0.0001)

    color_kind, color_value = _resolve_channel(
        material, vol_node.inputs.get("Color"), f"{image_prefix}_color", "sRGB",
    )
    if color_kind == 'image':
        # attenuationColor has no texture slot — use the baked mean.
        r = _image_mean_channel(color_value.image, 0)
        g = _image_mean_channel(color_value.image, 1)
        b = _image_mean_channel(color_value.image, 2)
        absorption.inputs["Color"].default_value = (r, g, b, 1.0)
    else:
        _apply_channel(tree, absorption.inputs["Color"], color_kind, color_value)

    # The exporter's get_socket(..., volume=True) only finds an Absorption node
    # linked to the active output's Volume input (search_node_tree.py's
    # check_if_is_linked_to_active_output). Relinking is safe: this is an
    # export-time material copy.
    tree.links.new(absorption.outputs["Volume"], output.inputs["Volume"])

    _apply_volume_emission(material, vol_node, image_prefix)


def _apply_volume_emission(material: bpy.types.Material, vol_node, image_prefix: str) -> None:
    strength_socket = vol_node.inputs.get("Emission Strength")
    if strength_socket is None:
        return
    strength_kind, strength_value = _resolve_channel(
        material, strength_socket, f"{image_prefix}_emitstrength", "Non-Color",
    )
    has_emission = strength_kind == 'image' or (strength_value or 0.0) > 0.0
    if not has_emission:
        return

    surface = find_principled_surface(material)
    if surface is None:
        return
    tree = material.node_tree
    _apply_channel(tree, surface.inputs["Emission Strength"], strength_kind, strength_value)
    color_kind, color_value = _resolve_channel(
        material, vol_node.inputs.get("Emission Color"), f"{image_prefix}_emitcolor", "sRGB",
    )
    _apply_channel(tree, surface.inputs["Emission Color"], color_kind, color_value)


def _apply_beer_lambert(image: bpy.types.Image, thickness: float) -> None:
    """Converts a baked raw-density image (R=G=B=density) to alpha in place:
    1 - exp(-density * thickness)."""
    count = len(image.pixels)
    buffer = array('f', bytes(4 * count))
    image.pixels.foreach_get(buffer)
    for i in range(0, count, 4):
        density = max(buffer[i], 0.0)
        alpha = 1.0 - math.exp(-density * thickness)
        buffer[i] = buffer[i + 1] = buffer[i + 2] = alpha
    image.pixels.foreach_set(buffer)
    image.update()


def _resolve_alpha(material: bpy.types.Material, density_socket, thickness: float, image_name: str):
    if density_socket is None or not density_socket.is_linked:
        density = max(density_socket.default_value, 0.0) if density_socket is not None else 0.0
        alpha = 1.0 - math.exp(-density * thickness)
        return 'factor', max(0.0, min(1.0, alpha))
    image_node = bake_socket_to_image_node(material, density_socket.links[0].from_socket, image_name, "Non-Color")
    _apply_beer_lambert(image_node.image, thickness)
    return 'image', image_node


def _build_flat_alpha_approximation(material: bpy.types.Material, thickness: float, image_prefix: str) -> None:
    """Module docstring, case 2."""
    tree = material.node_tree
    output = find_output(material)
    vol_node = find_volume_node(material)

    principled = tree.nodes.new("ShaderNodeBsdfPrincipled")
    tree.links.new(principled.outputs["BSDF"], output.inputs["Surface"])
    principled.inputs["Roughness"].default_value = 1.0
    principled.inputs["Metallic"].default_value = 0.0

    color_kind, color_value = _resolve_channel(
        material, vol_node.inputs.get("Color"), f"{image_prefix}_color", "sRGB",
    )
    _apply_channel(tree, principled.inputs["Base Color"], color_kind, color_value)

    alpha_kind, alpha_value = _resolve_alpha(
        material, vol_node.inputs.get("Density"), thickness, f"{image_prefix}_density",
    )
    _apply_channel(tree, principled.inputs["Alpha"], alpha_kind, alpha_value)

    _apply_volume_emission(material, vol_node, image_prefix)


def approximate_volume_materials(duplicate: bpy.types.Object) -> list:
    """Adds a glTF representation (module docstring) for each slot material on
    `duplicate` with a volume shader, on a per-slot material copy. `duplicate`
    must be the sole selected + active object.

    Copies `duplicate.data` only if still shared (`users > 1`), so it's
    correct whichever preprocessing step copied it first. Returns the
    material copies for cleanup_baked_materials().
    """
    if duplicate.type != "MESH":
        return []
    if not any(is_volume_material(slot.material) for slot in duplicate.material_slots):
        return []

    if duplicate.data.users > 1:
        duplicate.data = duplicate.data.copy()

    thickness = max(duplicate.dimensions)

    volume_materials = []
    original_active_index = duplicate.active_material_index
    for index, slot in enumerate(duplicate.material_slots):
        if not is_volume_material(slot.material):
            continue

        new_material = slot.material.copy()
        duplicate.data.materials[index] = new_material
        duplicate.active_material_index = index

        image_prefix = f"{_BAKE_IMAGE_PREFIX}_{index}"
        if _has_real_transmission(new_material):
            _add_volume_extension_nodes(new_material, thickness, image_prefix)
        else:
            _build_flat_alpha_approximation(new_material, thickness, image_prefix)
        volume_materials.append(new_material)

    duplicate.active_material_index = original_active_index
    return volume_materials
