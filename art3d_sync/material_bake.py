"""Bakes a material's procedural Base Color to a flat image texture before
export — glTF can only carry a flat baseColorFactor or a real Image Texture,
never an arbitrary shader node graph. Confirmed against this Blender's own
export_scene.gltf operator (bl_rna properties): no bake-related option exists
beyond export_bake_animation, so a Base Color fed by anything other than a
flat value or an existing Image Texture node is silently *omitted* from the
export rather than approximated — and an omitted baseColorFactor defaults to
glTF's own spec default, opaque white, not the node's own default_value.
Confirmed by decoding a real exported .glb: a material with Base Color wired
to a Color Ramp came out with no baseColorFactor key at all.

Only Base Color is baked here, not Roughness/Metallic/Normal — those are
overwhelmingly flat, unlinked values across the reference scene (one
exception each), and an unbaked Normal only costs bump micro-detail, not a
wrong color; baking them too is a reasonable follow-up, not this fix's job.
"""

from typing import Optional

import bpy

_BAKE_SIZE = 512
_BAKE_IMAGE_NAME = "__art3d_bake_base_color"


def _find_principled(material: bpy.types.Material) -> Optional[bpy.types.ShaderNodeBsdfPrincipled]:
    if not material.use_nodes or material.node_tree is None:
        return None
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeBsdfPrincipled":
            return node
    return None


def _needs_bake(material: Optional[bpy.types.Material]) -> bool:
    if material is None:
        return False
    principled = _find_principled(material)
    if principled is None:
        return False
    base_color = principled.inputs.get("Base Color")
    if base_color is None or not base_color.is_linked:
        return False
    # A direct Image Texture is already exportable as-is — only a graph
    # glTF genuinely can't represent (Color Ramp/Noise/Voronoi/Mix/...) needs
    # baking.
    return base_color.links[0].from_node.bl_idname != "ShaderNodeTexImage"


def bake_base_colors(duplicate: bpy.types.Object) -> list:
    """Bakes Base Color into a fresh Image Texture for every material slot on
    `duplicate` that needs it (see _needs_bake), swapping in an independent
    material *copy* per slot. `duplicate` must already be the sole selected +
    active object (gltf_exporter.py's own export_object_glb sets this up).

    Mutates `duplicate.data` to an independent mesh-data copy the first time
    any slot actually needs baking — up to that point it's still the cheap
    shared reference gltf_exporter.py's own duplication relies on, so objects
    with no procedural materials pay nothing extra. The real object this
    duplicate stands in for (and its real mesh/material data) is never
    touched, even momentarily.

    Returns the list of baked material copies (+ their baked images), for
    cleanup_baked_materials() to remove after export.
    """
    if duplicate.type != "MESH":
        return []
    if not any(_needs_bake(slot.material) for slot in duplicate.material_slots):
        return []
    if not duplicate.data.uv_layers:
        # No UVs to bake into — leave these materials as-is (glTF export
        # omits their Base Color, same as today) rather than fail the whole
        # object's sync over one unbakeable material.
        return []

    duplicate.data = duplicate.data.copy()

    baked_materials = []
    original_active_index = duplicate.active_material_index
    original_engine = bpy.context.scene.render.engine
    # A 'DIFFUSE'/COLOR-only bake reads each node graph's own (mostly
    # deterministic — noise/voronoi/color-ramp, not stochastic GI) output
    # directly, not a path-traced light transport result — it doesn't need
    # anywhere near the scene's own real render sample count (this file's
    # reference scene: 4096, meant for the *final* image's noise floor, not a
    # flat-color bake). Low, fixed sample count here instead, so exporting a
    # scene with many procedural materials stays fast; higher only smooths
    # per-pixel noise-texture antialiasing, which converges well before 4096.
    original_samples = bpy.context.scene.cycles.samples
    bpy.context.scene.render.engine = "CYCLES"
    bpy.context.scene.cycles.samples = 16
    try:
        for index, slot in enumerate(duplicate.material_slots):
            if not _needs_bake(slot.material):
                continue

            new_material = slot.material.copy()
            duplicate.data.materials[index] = new_material
            duplicate.active_material_index = index

            image = bpy.data.images.new(
                f"{_BAKE_IMAGE_NAME}_{index}", _BAKE_SIZE, _BAKE_SIZE
            )
            image_node = new_material.node_tree.nodes.new("ShaderNodeTexImage")
            image_node.image = image
            new_material.node_tree.nodes.active = image_node

            bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, margin=4)

            principled = _find_principled(new_material)
            # The graph that used to feed Base Color is now baked into
            # `image` — replace it with the baked texture so the exporter
            # sees a plain, representable Image Texture, not the original
            # (still-present-on-`new_material`, now-orphaned) node graph.
            new_material.node_tree.links.new(
                image_node.outputs["Color"], principled.inputs["Base Color"]
            )
            baked_materials.append(new_material)
    finally:
        bpy.context.scene.render.engine = original_engine
        bpy.context.scene.cycles.samples = original_samples
        duplicate.active_material_index = original_active_index

    return baked_materials


def cleanup_baked_materials(materials: list) -> None:
    """Removes every material (and its baked image) bake_base_colors()
    returned — call from export_object_glb's own finally block, same as its
    duplicate/duplicate_armature cleanup."""
    for material in materials:
        for node in material.node_tree.nodes:
            if node.bl_idname == "ShaderNodeTexImage" and node.image is not None:
                bpy.data.images.remove(node.image)
        bpy.data.materials.remove(material)


def cleanup_duplicate_mesh(mesh: bpy.types.Mesh) -> None:
    """Removes a mesh-data copy bake_base_colors() made, once nothing still
    references it — call *after* the duplicate object itself has been
    removed (that drop is what brings this to 0 users; calling any earlier
    would fail). A no-op if `mesh` still has users (the fast path where
    bake_base_colors() never had to copy anything, or this same mesh is
    somehow still referenced elsewhere) — without this leaving an orphaned
    mesh datablock behind on every baked send, across a long-running Blender
    session sending many objects."""
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)
