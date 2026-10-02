"""Bakes a material's graph-driven Principled inputs to image textures before
export. glTF carries only flat factors or Image Textures, and Blender's glTF
exporter has no bake option: a graph-fed input is silently omitted (an omitted
baseColorFactor becomes glTF's default white, not the node's value).

- Base Color / Roughness: DIFFUSE(COLOR) / ROUGHNESS passes; view-dependent
  graphs need the Emission-rewire bake instead (`_has_view_dependent_node`).
- Normal: a Bump or procedural graph has no glTF equivalent; Image Texture ->
  Normal Map exports natively and is left alone.
- Emission: glTF textures only Emission Color (io_scene_gltf2's
  material/extensions/emission.py reads Strength as a plain factor), so the
  combined Color*Strength is baked with type='EMIT' — which reads Principled's
  emission off the unmodified material — into Emission Color, Strength = 1.0.
- Metallic: not baked — no dedicated bake pass. If a material needs it, bake
  via shader_bake.bake_socket_to_image_node.
"""

from typing import Optional

import bpy

from .shader_bake import (
    bake_socket_to_image_node,
    find_principled_surface,
    is_bake_image,
    new_bake_image,
)

_BAKE_IMAGE_PREFIX = "__art3d_bake"

# These passes read input values without light transport (DIFFUSE +
# {'COLOR'} is pure albedo), so a low fixed count suffices; more samples only
# smooth procedural-texture antialiasing.
_BAKE_SAMPLES = 16


def _needs_factor_bake(socket) -> bool:
    """Flat values and direct Image Textures export as-is; only a node graph
    needs baking."""
    if socket is None or not socket.is_linked:
        return False
    return socket.links[0].from_node.bl_idname != "ShaderNodeTexImage"


def _needs_normal_bake(socket) -> bool:
    """True unless Normal is unlinked or fed by the chain the exporter handles
    natively: Image Texture -> Normal Map -> Normal."""
    if socket is None or not socket.is_linked:
        return False
    from_node = socket.links[0].from_node
    if from_node.bl_idname != "ShaderNodeNormalMap":
        return True
    color_input = from_node.inputs.get("Color")
    if color_input is None or not color_input.is_linked:
        return True
    return color_input.links[0].from_node.bl_idname != "ShaderNodeTexImage"


def _has_view_dependent_node(socket, seen: Optional[set] = None) -> bool:
    """True if the upstream graph has a Fresnel or Layer Weight node. A
    DIFFUSE/ROUGHNESS pass has no camera ray for these and bakes solid black;
    the Emission-rewire bake (bake_socket_to_image_node) evaluates them."""
    if seen is None:
        seen = set()
    if socket is None or not socket.is_linked:
        return False
    node = socket.links[0].from_node
    if id(node) in seen:
        return False
    seen.add(id(node))
    if node.bl_idname in ("ShaderNodeFresnel", "ShaderNodeLayerWeight"):
        return True
    return any(_has_view_dependent_node(input_socket, seen) for input_socket in node.inputs)


def _needs_emission_bake(principled: bpy.types.ShaderNodeBsdfPrincipled) -> bool:
    """Either input graph-driven means the Color*Strength product is baked."""
    return _needs_factor_bake(principled.inputs.get("Emission Color")) or _needs_factor_bake(
        principled.inputs.get("Emission Strength")
    )


def _needs_bake(material: Optional[bpy.types.Material]) -> bool:
    if material is None:
        return False
    principled = find_principled_surface(material)
    if principled is None:
        return False
    return (
        _needs_factor_bake(principled.inputs.get("Base Color"))
        or _needs_factor_bake(principled.inputs.get("Roughness"))
        or _needs_normal_bake(principled.inputs.get("Normal"))
        or _needs_emission_bake(principled)
    )


def _activate_bake_target(material: bpy.types.Material, image: bpy.types.Image) -> None:
    """Bake writes to the node tree's active Image Texture node."""
    image_node = material.node_tree.nodes.new("ShaderNodeTexImage")
    image_node.image = image
    material.node_tree.nodes.active = image_node


def _bake_factor_channel(
    material: bpy.types.Material,
    principled: bpy.types.ShaderNodeBsdfPrincipled,
    input_name: str,
    bake_type: str,
    pass_filter: set,
    image_name: str,
    colorspace: str,
) -> None:
    socket = principled.inputs[input_name]
    if _has_view_dependent_node(socket):
        image_node = bake_socket_to_image_node(
            material, socket.links[0].from_socket, image_name, colorspace
        )
    else:
        image = new_bake_image(image_name, colorspace)
        _activate_bake_target(material, image)
        if pass_filter:
            bpy.ops.object.bake(type=bake_type, pass_filter=pass_filter, margin=4)
        else:
            bpy.ops.object.bake(type=bake_type, margin=4)
        # Pack immediately — see shader_bake.bake_socket_to_image_node.
        image.pack()
        image_node = material.node_tree.nodes.active
    material.node_tree.links.new(image_node.outputs["Color"], principled.inputs[input_name])


def _bake_normal_channel(
    material: bpy.types.Material,
    principled: bpy.types.ShaderNodeBsdfPrincipled,
    image_name: str,
) -> None:
    image = new_bake_image(image_name, "Non-Color")
    _activate_bake_target(material, image)
    # Tangent space, R=+X/G=+Y/B=+Z is glTF's normalTexture convention
    # (OpenGL-style, Y+), so no channel remap.
    bpy.ops.object.bake(
        type="NORMAL",
        normal_space="TANGENT",
        normal_r="POS_X",
        normal_g="POS_Y",
        normal_b="POS_Z",
        margin=4,
    )
    image.pack()
    image_node = material.node_tree.nodes.active
    # The Normal Map node decodes 0..1 RGB to a tangent-space normal — the
    # chain the exporter recognizes natively.
    normal_map_node = material.node_tree.nodes.new("ShaderNodeNormalMap")
    normal_map_node.space = "TANGENT"
    material.node_tree.links.new(image_node.outputs["Color"], normal_map_node.inputs["Color"])
    material.node_tree.links.new(normal_map_node.outputs["Normal"], principled.inputs["Normal"])


def _bake_emission_channel(
    material: bpy.types.Material,
    principled: bpy.types.ShaderNodeBsdfPrincipled,
    image_name: str,
) -> None:
    """Bakes the combined Color*Strength (see the module docstring)."""
    image = new_bake_image(image_name, "sRGB")
    _activate_bake_target(material, image)
    bpy.ops.object.bake(type="EMIT", margin=4)
    image.pack()
    image_node = material.node_tree.nodes.active
    material.node_tree.links.new(image_node.outputs["Color"], principled.inputs["Emission Color"])
    # Unlink too: a linked socket ignores default_value, so its graph would
    # apply Strength again on top of the baked product.
    strength_input = principled.inputs["Emission Strength"]
    if strength_input.is_linked:
        material.node_tree.links.remove(strength_input.links[0])
    strength_input.default_value = 1.0


def bake_procedural_channels(duplicate: bpy.types.Object) -> list:
    """Bakes graph-driven Base Color/Roughness/Normal/Emission inputs into
    image textures, on a per-slot material copy. `duplicate` must be the sole
    selected + active object.

    `duplicate.data` is copied only once some slot needs baking, so objects
    without procedural materials keep the cheap shared mesh; the original
    object's data is never touched.

    Returns the material copies for cleanup_baked_materials().
    """
    if duplicate.type != "MESH":
        return []
    if not any(_needs_bake(slot.material) for slot in duplicate.material_slots):
        return []
    if not duplicate.data.uv_layers:
        # No UVs to bake into — export as-is rather than fail the object.
        return []

    duplicate.data = duplicate.data.copy()

    baked_materials = []
    original_active_index = duplicate.active_material_index
    original_engine = bpy.context.scene.render.engine
    original_samples = bpy.context.scene.cycles.samples
    bpy.context.scene.render.engine = "CYCLES"
    bpy.context.scene.cycles.samples = _BAKE_SAMPLES
    try:
        for index, slot in enumerate(duplicate.material_slots):
            if not _needs_bake(slot.material):
                continue

            new_material = slot.material.copy()
            duplicate.data.materials[index] = new_material
            duplicate.active_material_index = index
            principled = find_principled_surface(new_material)

            base_color = principled.inputs.get("Base Color")
            if _needs_factor_bake(base_color):
                _bake_factor_channel(
                    new_material,
                    principled,
                    "Base Color",
                    "DIFFUSE",
                    {"COLOR"},
                    f"{_BAKE_IMAGE_PREFIX}_basecolor_{index}",
                    "sRGB",
                )

            roughness = principled.inputs.get("Roughness")
            if _needs_factor_bake(roughness):
                _bake_factor_channel(
                    new_material,
                    principled,
                    "Roughness",
                    "ROUGHNESS",
                    set(),
                    f"{_BAKE_IMAGE_PREFIX}_roughness_{index}",
                    "Non-Color",
                )

            normal = principled.inputs.get("Normal")
            if _needs_normal_bake(normal):
                _bake_normal_channel(new_material, principled, f"{_BAKE_IMAGE_PREFIX}_normal_{index}")

            if _needs_emission_bake(principled):
                _bake_emission_channel(
                    new_material, principled, f"{_BAKE_IMAGE_PREFIX}_emission_{index}"
                )

            baked_materials.append(new_material)
    finally:
        bpy.context.scene.render.engine = original_engine
        bpy.context.scene.cycles.samples = original_samples
        duplicate.active_material_index = original_active_index

    return baked_materials


def cleanup_baked_materials(materials: list) -> None:
    """Removes the preprocessing materials and the bake images their Image
    Texture nodes reference. The user's own images stay: the copies share
    them with the original materials."""
    for material in materials:
        for node in material.node_tree.nodes:
            if node.bl_idname != "ShaderNodeTexImage" or node.image is None:
                continue
            if is_bake_image(node.image):
                bpy.data.images.remove(node.image)
        bpy.data.materials.remove(material)


def cleanup_duplicate_mesh(mesh) -> None:
    """Frees the preprocessing's mesh-data copy — call after removing the
    duplicate object, which drops it to 0 users. No-op while it still has
    users (nothing was copied: it's the original's shared mesh) or for
    non-Mesh data (only MESH objects get their data copied)."""
    if not isinstance(mesh, bpy.types.Mesh):
        return
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)
