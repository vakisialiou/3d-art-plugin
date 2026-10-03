"""Shared Cycles-bake plumbing for material_bake.py, material_flatten.py and
material_volume.py (find_active_output() also serves world_sync.py).

find_principled_surface() walks from Material Output's Surface input — never
"the first Principled by type", which can pick a disconnected node or one half
of a Mix Shader. `None` means Surface isn't a single Principled BSDF
(material_flatten.py handles that).
"""

from typing import Optional

import bpy

BAKE_SIZE = 512
BAKE_SAMPLES = 16

# Marks the images new_bake_image() creates, so cleanup removes only those: a
# material.copy() shares the user's own Image datablocks, it doesn't copy them.
_BAKE_IMAGE_TAG = "art3d_bake"


def find_active_output(node_tree: bpy.types.NodeTree, bl_idname: str) -> Optional[bpy.types.Node]:
    """The active output node of type `bl_idname`, else the first one."""
    output = None
    for node in node_tree.nodes:
        if node.bl_idname == bl_idname:
            if node.is_active_output:
                return node
            if output is None:
                output = node
    return output


def find_output(material: bpy.types.Material) -> Optional[bpy.types.ShaderNodeOutputMaterial]:
    return find_active_output(material.node_tree, "ShaderNodeOutputMaterial")


def find_principled_surface(
    material: bpy.types.Material,
) -> Optional[bpy.types.ShaderNodeBsdfPrincipled]:
    output = find_output(material)
    if output is None:
        return None
    surface = output.inputs.get("Surface")
    if surface is None or not surface.is_linked:
        return None
    node = surface.links[0].from_node
    if node.bl_idname != "ShaderNodeBsdfPrincipled":
        return None
    return node


def new_bake_image(name: str, colorspace: str) -> bpy.types.Image:
    image = bpy.data.images.new(name, BAKE_SIZE, BAKE_SIZE)
    image.colorspace_settings.name = colorspace
    image[_BAKE_IMAGE_TAG] = True
    return image


def is_bake_image(image: bpy.types.Image) -> bool:
    return bool(image.get(_BAKE_IMAGE_TAG))


def activate_bake_target(
    material: bpy.types.Material, image: bpy.types.Image
) -> bpy.types.ShaderNodeTexImage:
    """Bake writes to the node tree's active Image Texture node — call once
    per pass, each with a fresh image."""
    image_node = material.node_tree.nodes.new("ShaderNodeTexImage")
    image_node.image = image
    material.node_tree.nodes.active = image_node
    return image_node


class cycles_bake_settings:
    """Context manager: Cycles at BAKE_SAMPLES for one bake call (these passes
    read node values with no light transport, so few samples suffice);
    restores the scene's engine/samples on exit, even if the bake raises."""

    def __enter__(self) -> None:
        self._engine = bpy.context.scene.render.engine
        self._samples = bpy.context.scene.cycles.samples
        bpy.context.scene.render.engine = "CYCLES"
        bpy.context.scene.cycles.samples = BAKE_SAMPLES

    def __exit__(self, *exc_info: object) -> None:
        bpy.context.scene.render.engine = self._engine
        bpy.context.scene.cycles.samples = self._samples


def bake_socket_to_image_node(
    material: bpy.types.Material,
    output_socket: bpy.types.NodeSocket,
    image_name: str,
    colorspace: str,
) -> bpy.types.ShaderNodeTexImage:
    """Bakes `output_socket`'s resolved value (scalars broadcast across RGB)
    into a fresh image via a temporary Emission shader on Material Output's
    Surface, then restores the original Surface link."""
    tree = material.node_tree
    output = find_output(material)
    surface_input = output.inputs["Surface"]
    original_from = surface_input.links[0].from_socket if surface_input.is_linked else None

    emission = tree.nodes.new("ShaderNodeEmission")
    tree.links.new(output_socket, emission.inputs["Color"])
    tree.links.new(emission.outputs["Emission"], surface_input)

    image = new_bake_image(image_name, colorspace)
    image_node = activate_bake_target(material, image)

    with cycles_bake_settings():
        bpy.ops.object.bake(type="EMIT", margin=4)
    # Pack immediately: an unpacked bake result can read back blank after
    # further bakes or datablock removals (Blender's "save it externally or
    # pack it" bake message means it).
    image.pack()

    tree.nodes.remove(emission)
    tree.links.new(original_from, surface_input)

    return image_node
