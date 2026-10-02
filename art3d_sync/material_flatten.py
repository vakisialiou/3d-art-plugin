"""Replaces a material whose Surface isn't one directly-wired Principled BSDF
(Mix Shader, bare Glossy, Add Shader, ...) with a synthetic single-Principled
material baked from it. Must run before material_bake.py, which only handles a
Surface that already is one Principled.

Base Color/Roughness/Normal/Emission bake generically: DIFFUSE+COLOR /
ROUGHNESS / NORMAL / EMIT read the evaluated shading result, whatever Surface
is. Metallic has no bake pass, so it's reconstructed only for a Mix Shader of
exactly two Principled BSDFs — mix(metallic_A, metallic_B, Fac) via
shader_bake.bake_socket_to_image_node; any other shape gets flat Metallic 0.0.
"""

from typing import Optional

import bpy

from .shader_bake import (
    activate_bake_target,
    bake_socket_to_image_node,
    cycles_bake_settings,
    find_output,
    find_principled_surface,
    new_bake_image,
)

_BAKE_IMAGE_PREFIX = "__art3d_flatten"


def _needs_flatten(material: Optional[bpy.types.Material]) -> bool:
    if material is None:
        return False
    if not material.use_nodes or material.node_tree is None:
        return False
    return find_principled_surface(material) is None


def _bake_render_channel(
    material: bpy.types.Material,
    bake_type: str,
    pass_filter: set,
    image_name: str,
    colorspace: str,
) -> bpy.types.Image:
    """Bakes `bake_type` from `material` as it currently renders, no rewiring."""
    image = new_bake_image(image_name, colorspace)
    activate_bake_target(material, image)
    with cycles_bake_settings():
        if pass_filter:
            bpy.ops.object.bake(type=bake_type, pass_filter=pass_filter, margin=4)
        else:
            bpy.ops.object.bake(type=bake_type, margin=4)
    # Pack immediately — see shader_bake.bake_socket_to_image_node.
    image.pack()
    return image


def _find_mix_of_two_principled(material: bpy.types.Material):
    """(first, second, Fac) for Surface <- Mix Shader <- two Principled BSDFs
    (Fac=0 → first, Fac=1 → second), else None."""
    output = find_output(material)
    if output is None:
        return None
    surface = output.inputs.get("Surface")
    if surface is None or not surface.is_linked:
        return None
    mix = surface.links[0].from_node
    if mix.bl_idname != "ShaderNodeMixShader":
        return None

    shader_inputs = [socket for socket in mix.inputs if socket.type == "SHADER"]
    if len(shader_inputs) != 2:
        return None
    principled_nodes = []
    for shader_input in shader_inputs:
        if not shader_input.is_linked:
            return None
        node = shader_input.links[0].from_node
        if node.bl_idname != "ShaderNodeBsdfPrincipled":
            return None
        principled_nodes.append(node)

    fac = mix.inputs.get("Fac")
    if fac is None:
        return None
    return principled_nodes[0], principled_nodes[1], fac


def _wire_scalar_source(tree: bpy.types.NodeTree, source_socket, target_socket) -> None:
    """Feeds `target_socket` (a MixRGB input) from `source_socket`'s link
    source if linked (a scalar into a Color input broadcasts as R=G=B), else
    from its flat value — broadcast across RGB into a Color input, as-is into
    the float Fac."""
    if source_socket.is_linked:
        tree.links.new(source_socket.links[0].from_socket, target_socket)
        return
    value = source_socket.default_value
    if target_socket.type == "RGBA":
        target_socket.default_value = (value, value, value, 1.0)
    else:
        target_socket.default_value = value


def _bake_metallic(material: bpy.types.Material, image_name: str) -> Optional[bpy.types.Image]:
    found = _find_mix_of_two_principled(material)
    if found is None:
        return None
    principled_a, principled_b, fac = found

    tree = material.node_tree
    mix_node = tree.nodes.new("ShaderNodeMixRGB")
    mix_node.blend_type = "MIX"
    _wire_scalar_source(tree, fac, mix_node.inputs["Fac"])
    _wire_scalar_source(tree, principled_a.inputs["Metallic"], mix_node.inputs["Color1"])
    _wire_scalar_source(tree, principled_b.inputs["Metallic"], mix_node.inputs["Color2"])

    image_node = bake_socket_to_image_node(
        material, mix_node.outputs["Color"], image_name, "Non-Color"
    )
    tree.nodes.remove(mix_node)
    return image_node.image


def _build_flat_principled(
    name: str,
    base_color: bpy.types.Image,
    roughness: bpy.types.Image,
    normal: bpy.types.Image,
    emission: bpy.types.Image,
    metallic: Optional[bpy.types.Image],
) -> bpy.types.Material:
    """Always a brand-new material: rebuilding the bake source's tree in place
    zeroes the baked images once their Image Texture nodes are removed.
    `use_nodes = True` creates the Principled + Output pair reused here."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    principled = next(n for n in tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")

    def _wire_image(image: bpy.types.Image, input_name: str, colorspace: str) -> None:
        image.colorspace_settings.name = colorspace
        node = tree.nodes.new("ShaderNodeTexImage")
        node.image = image
        tree.links.new(node.outputs["Color"], principled.inputs[input_name])

    _wire_image(base_color, "Base Color", "sRGB")
    _wire_image(roughness, "Roughness", "Non-Color")
    _wire_image(emission, "Emission Color", "sRGB")
    principled.inputs["Emission Strength"].default_value = 1.0

    normal.colorspace_settings.name = "Non-Color"
    normal_tex = tree.nodes.new("ShaderNodeTexImage")
    normal_tex.image = normal
    normal_map = tree.nodes.new("ShaderNodeNormalMap")
    normal_map.space = "TANGENT"
    tree.links.new(normal_tex.outputs["Color"], normal_map.inputs["Color"])
    tree.links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])

    if metallic is not None:
        _wire_image(metallic, "Metallic", "Non-Color")
    else:
        principled.inputs["Metallic"].default_value = 0.0

    return material


def flatten_incompatible_surfaces(duplicate: bpy.types.Object, created: list) -> None:
    """Swaps each slot material on `duplicate` whose Surface isn't a single
    Principled BSDF for a baked single-Principled one. `duplicate` must be the
    sole selected + active object; run before bake_procedural_channels and
    approximate_volume_materials.

    Copies `duplicate.data` first if it's still shared (`users > 1`).
    Appends each material it creates to `created` the moment it exists, for
    cleanup_baked_materials() — even if a later bake raises.
    """
    if duplicate.type != "MESH":
        return
    if not any(_needs_flatten(slot.material) for slot in duplicate.material_slots):
        return
    if not duplicate.data.uv_layers:
        # No UVs to bake into — export as-is rather than fail the object.
        return

    if duplicate.data.users > 1:
        duplicate.data = duplicate.data.copy()

    original_active_index = duplicate.active_material_index
    try:
        for index, slot in enumerate(duplicate.material_slots):
            if not _needs_flatten(slot.material):
                continue

            # Transient copy, in the slot only so the bake targets it; removed
            # after baking (its images live on in the synthetic material).
            # Tracked until then, so a failed bake still frees its images.
            bake_source = slot.material.copy()
            created.append(bake_source)
            duplicate.data.materials[index] = bake_source
            duplicate.active_material_index = index

            prefix = f"{_BAKE_IMAGE_PREFIX}_{index}"
            base_color = _bake_render_channel(
                bake_source, "DIFFUSE", {"COLOR"}, f"{prefix}_basecolor", "sRGB"
            )
            roughness = _bake_render_channel(
                bake_source, "ROUGHNESS", set(), f"{prefix}_roughness", "Non-Color"
            )
            normal = _bake_render_channel(
                bake_source, "NORMAL", set(), f"{prefix}_normal", "Non-Color"
            )
            emission = _bake_render_channel(
                bake_source, "EMIT", set(), f"{prefix}_emission", "sRGB"
            )
            metallic = _bake_metallic(bake_source, f"{prefix}_metallic")

            new_material = _build_flat_principled(
                f"{bake_source.name}_flattened", base_color, roughness, normal, emission, metallic
            )
            created.append(new_material)
            created.remove(bake_source)
            bpy.data.materials.remove(bake_source)
            duplicate.data.materials[index] = new_material
    finally:
        duplicate.active_material_index = original_active_index
