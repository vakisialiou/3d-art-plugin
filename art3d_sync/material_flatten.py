"""Flattens a material whose Surface isn't a single, directly-connected
Principled BSDF into a synthetic one that is — glTF (and this project's own
gltf_exporter.py/material_bake.py) has no way to represent an arbitrary
shader network, only a single PBR-shaped material. Runs *before*
material_bake.py's own bake_procedural_channels(), which only ever handles a
material that already has exactly one Principled BSDF driving Surface
(detected via shader_bake.find_principled_surface) — a Mix Shader material
has no such node at all, so that function already does nothing for it on its
own; this is what actually replaces it.

Base Color/Roughness/Normal/Emission are genuinely generic and need no
per-material-shape logic at all: baking these (DIFFUSE+COLOR / ROUGHNESS /
NORMAL / EMIT respectively) reads the material's real, already-evaluated
shading result at each point, not any one node's own input value — confirmed
empirically against this project's own Mat_Iron_Rusty (a real Mix Shader
blending two Principled BSDFs): a DIFFUSE+COLOR bake shows genuine per-pixel
variance matching the blend mask, not the flat value either Principled
node's own Base Color input holds, and a ROUGHNESS bake likewise shows the
real transition between the two nodes' values. This works regardless of what
Surface actually is — a Mix Shader, a bare Glossy/Diffuse/Toon BSDF, an Add
Shader, anything — so it covers a material shape this project's reference
scene doesn't even have yet, not just the two Mix Shader cases audited here.

Metallic is the one channel with no bake pass at all (material_bake.py's own
docstring) and, unlike the other four, has no single "real" rendered value
to read off an arbitrary blend either — reconstructed explicitly, and only
for the one shape actually recognized: a Mix Shader blending exactly two
Principled BSDFs (this scene's own Mat_Iron_Rusty/Mat_Copper_Patina, and
Blender's standard "layered/weathered material" authoring pattern more
generally — a base material overlaid with rust/patina/damage through a
procedural mask). Bakes mix(metallic_A, metallic_B, Fac) using the Mix
Shader's own real Fac source, via the same Emission-shader-rewire trick
material_volume.py already uses for its own Volume sockets
(shader_bake.bake_socket_to_image_node). Any other Surface shape (anything
that isn't this recognized 2-Principled Mix Shader) falls back to a flat
Metallic 0.0 — an honest, disclosed simplification, not a silent guess, and
still strictly better than today's alternative for that shape (an arbitrary,
unrelated node's value, or the material dropped from the export outright).
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
    """Bakes `bake_type` from `material` exactly as it currently renders —
    no rewiring, no assumption about what Surface is — into a fresh image."""
    image = new_bake_image(image_name, colorspace)
    activate_bake_target(material, image)
    with cycles_bake_settings():
        if pass_filter:
            bpy.ops.object.bake(type=bake_type, pass_filter=pass_filter, margin=4)
        else:
            bpy.ops.object.bake(type=bake_type, margin=4)
    # See shader_bake.bake_socket_to_image_node's own comment: an unpacked
    # bake result can read back blank once more bpy.ops.object.bake calls
    # or datablock removals happen before anything consumes it — this
    # function's own caller does several more of both (four more bakes, a
    # material removal) before export ever reads these pixels.
    image.pack()
    return image


def _find_mix_of_two_principled(material: bpy.types.Material):
    """The one Metallic-recoverable shape this recognizes: Material
    Output.Surface <- a Mix Shader <- two Principled BSDFs (Blender's own
    real Fac=0->first input/Fac=1->second input convention — verified via
    bpy introspection, not assumed). `None` for anything else, including a
    Mix Shader blending anything other than two Principled BSDFs — callers
    fall back to a flat Metallic in that case."""
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
    """Feeds `target_socket` (a MixRGB Color1/Color2 input) from whatever
    actually drives `source_socket` — the link's own source if linked
    (Blender broadcasts a scalar output into a Color input as R=G=B,
    confirmed empirically, same as shader_bake.bake_socket_to_image_node's
    own Emission.Color rewiring), or its flat value broadcast across RGB
    otherwise."""
    if source_socket.is_linked:
        tree.links.new(source_socket.links[0].from_socket, target_socket)
        return
    value = source_socket.default_value
    target_socket.default_value = (value, value, value, 1.0)


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
    """A brand-new material, never the bake source's own tree: clearing and
    rebuilding *that* tree in place (this function's own first version)
    discarded the just-baked pixel data the moment its Image Texture nodes
    were removed — confirmed empirically (baked images read back correctly
    immediately after each bake call, but as all-zero once the source
    tree's nodes were cleared and rebuilt afterward, even reusing the exact
    same `bpy.types.Image` objects). A material created fresh via
    `use_nodes = True` already gets a default Principled BSDF + Material
    Output pair — reused directly rather than adding a second one."""
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


def flatten_incompatible_surfaces(duplicate: bpy.types.Object) -> list:
    """For every material slot on `duplicate` whose Surface isn't a single
    Principled BSDF, bakes the whole material's real rendered look into a
    fresh, synthetic single-Principled replacement — swapping in an
    independent material *copy* per slot, same discipline as
    material_bake.py's own bake_procedural_channels. `duplicate` must
    already be the sole selected + active object (gltf_exporter.py's own
    export_object_glb sets this up, same precondition bake_procedural_channels
    and approximate_volume_materials rely on). Must run *before* either of
    those two — see module docstring.

    Copies `duplicate.data` to an independent datablock the first time any
    slot actually needs this — checked via `.users > 1`, same reasoning as
    approximate_volume_materials's own doc comment (this module runs first
    in practice, but stays correct regardless of order).

    Returns the list of newly-created materials, for cleanup_baked_materials()
    (material_bake.py — same shape: an image per ShaderNodeTexImage node plus
    the material itself) to remove after export.
    """
    if duplicate.type != "MESH":
        return []
    if not any(_needs_flatten(slot.material) for slot in duplicate.material_slots):
        return []
    if not duplicate.data.uv_layers:
        # No UVs to bake into — leave these materials as-is, same fallback
        # bake_procedural_channels uses, rather than fail the whole object's
        # sync over one unbakeable material.
        return []

    if duplicate.data.users > 1:
        duplicate.data = duplicate.data.copy()

    flattened_materials = []
    original_active_index = duplicate.active_material_index
    try:
        for index, slot in enumerate(duplicate.material_slots):
            if not _needs_flatten(slot.material):
                continue

            # A transient copy, live in the slot only for bake targeting —
            # never returned, never exported: removed (material only, not
            # the images its bake-target nodes reference — those outlive it
            # in the synthetic material built below) the moment baking is
            # done.
            bake_source = slot.material.copy()
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
            bpy.data.materials.remove(bake_source)
            duplicate.data.materials[index] = new_material
            flattened_materials.append(new_material)
    finally:
        duplicate.active_material_index = original_active_index

    return flattened_materials
