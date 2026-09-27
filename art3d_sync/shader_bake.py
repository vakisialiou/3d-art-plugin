"""Shared Cycles-bake plumbing used by material_bake.py, material_volume.py,
and material_flatten.py — every one of them, at some point, needs either "the
real Material Output node" or "bake an arbitrary socket's resolved value
(not one node's own input) into an image via a temporary Emission shader
wired to Surface, then restore Surface". One implementation here instead of
three near-identical copies.

find_principled_surface() is the one correct way to find "the Principled
BSDF actually driving this material's real rendered look" — walking from
Material Output's own Surface input, never "the first ShaderNodeBsdfPrincipled
found by type" (material_bake.py's own original approach, and a real bug: a
material with an unused/disconnected extra Principled node, or one built
from a Mix Shader blending two of them — this project's own
Mat_Iron_Rusty/Mat_Copper_Patina — silently misrepresented the wrong one).
`None` means Surface isn't a single Principled BSDF at all; see
material_flatten.py for what handles that case.
"""

from typing import Optional

import bpy

BAKE_SIZE = 512
BAKE_SAMPLES = 16


def find_output(material: bpy.types.Material) -> Optional[bpy.types.ShaderNodeOutputMaterial]:
    output = None
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeOutputMaterial":
            if node.is_active_output:
                return node
            if output is None:
                output = node
    return output


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
    return image


def activate_bake_target(
    material: bpy.types.Material, image: bpy.types.Image
) -> bpy.types.ShaderNodeTexImage:
    """Every bake pass reads/writes whichever Image Texture node is the node
    tree's own active node — callers doing several passes on the same
    material call this once per pass, re-pointing at a fresh image each
    time."""
    image_node = material.node_tree.nodes.new("ShaderNodeTexImage")
    image_node.image = image
    material.node_tree.nodes.active = image_node
    return image_node


class cycles_bake_settings:
    """Context manager: switches to this project's fixed, fast Cycles bake
    settings (real bake pass types — a light-transport-free read of a node
    graph's own resolved values, not the scene's real render — never need
    anywhere near the scene's own real sample count) for the duration of one
    `bpy.ops.object.bake(...)` call, restoring whatever the scene had before
    on exit even if the bake itself raises."""

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
    """Bakes `output_socket`'s resolved value (color or scalar, broadcast
    across RGB) into a fresh image, via a temporary Emission shader wired to
    Material Output's Surface. Restores whatever Surface pointed to before
    this call once done — never replaces or disconnects the material's real
    Surface permanently, whatever it is."""
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
    # Confirmed empirically: an unpacked bake result can read back as blank
    # once enough further bpy.ops.object.bake calls or datablock removals
    # happen before anything else consumes it (Blender's own "Baking map
    # saved to internal image, save it externally or pack it" info message,
    # printed on every bake, is a literal, load-bearing hint — not just
    # informational chatter). Packing immediately makes the pixel data
    # durable regardless of what runs afterward.
    image.pack()

    tree.nodes.remove(emission)
    tree.links.new(original_from, surface_input)

    return image_node
