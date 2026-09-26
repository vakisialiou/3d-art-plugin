"""Bakes a material's procedural inputs to flat image textures before export —
glTF can only carry a flat factor or a real Image Texture, never an arbitrary
shader node graph. Confirmed against this Blender's own export_scene.gltf
operator (bl_rna properties): no bake-related option exists beyond
export_bake_animation, so an input fed by anything other than a flat value or
an existing Image Texture node is silently *omitted* from the export rather
than approximated — and an omitted baseColorFactor defaults to glTF's own
spec default, opaque white, not the node's own default_value. Confirmed by
decoding a real exported .glb: a material with Base Color wired to a Color
Ramp came out with no baseColorFactor key at all.

Which channels actually need this was decided from a real audit of this
project's reference scene (materials-demo.blend, 65 materials), not guessed:
- Base Color: ~20 materials feed it through a Color Ramp/Mix/Brick graph.
- Normal: the dominant case — most materials feed a Bump node from a
  procedural texture (Wave/Noise/Voronoi/Checker/Mix), which has no glTF
  equivalent at all; a few feed a real Normal Map node instead, which *is*
  natively exportable as long as its own Color input is a plain Image
  Texture (the standard Blender-to-glTF normal-map workflow) — only the
  procedural cases need baking.
- Roughness: 2 materials (a Color Ramp, a Map Range).
- Metallic: every material in the reference scene has it flat. Deliberately
  NOT baked here — unlike Base Color/Roughness, Blender's own bake operator
  (bpy.ops.object.bake, confirmed via its real bl_rna `type` enum) has no
  dedicated Metallic pass; the only way to bake an arbitrary socket like this
  is rewiring it through a temporary Emission shader and baking type='EMIT',
  a real technique but a separate, untested code path with nothing in this
  scene to exercise or verify it against. Add it the same way as Roughness
  below if a real material ever needs it.
"""

from typing import Optional

import bpy

_BAKE_SIZE = 512
_BAKE_IMAGE_PREFIX = "__art3d_bake"

# Real Cycles bake pass types (bpy.ops.object.bake's own bl_rna `type` enum,
# not from memory) that read a Principled BSDF input's own value directly —
# DIFFUSE+pass_filter={'COLOR'} isolates the albedo, ROUGHNESS is its own
# dedicated pass. Neither involves the scene's real light transport, so
# neither needs anywhere near the scene's own real render sample count (this
# file's reference scene: 4096, meant for the *final* image's noise floor) —
# a low, fixed count keeps exporting a scene with many procedural materials
# fast; higher only smooths per-pixel noise-texture antialiasing, which
# converges well before 4096.
_BAKE_SAMPLES = 16


def _find_principled(material: bpy.types.Material) -> Optional[bpy.types.ShaderNodeBsdfPrincipled]:
    if not material.use_nodes or material.node_tree is None:
        return None
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeBsdfPrincipled":
            return node
    return None


def _needs_factor_bake(socket) -> bool:
    """Base Color / Roughness: a flat value is already the constant glTF
    exports, and a direct Image Texture is already a plain texture glTF
    exports as-is — only a real node graph (Color Ramp/Noise/Mix/Brick/Map
    Range/...) needs baking."""
    if socket is None or not socket.is_linked:
        return False
    return socket.links[0].from_node.bl_idname != "ShaderNodeTexImage"


def _needs_normal_bake(socket) -> bool:
    """True unless Normal is unlinked (the common case — no normal map at
    all, nothing to bake) or fed by the one chain Blender's own glTF exporter
    recognizes natively: Image Texture -> Normal Map node -> Normal. A Bump
    node (height-based, no glTF equivalent at all) or a Normal Map node fed
    by anything other than a plain Image Texture both need baking."""
    if socket is None or not socket.is_linked:
        return False
    from_node = socket.links[0].from_node
    if from_node.bl_idname != "ShaderNodeNormalMap":
        return True
    color_input = from_node.inputs.get("Color")
    if color_input is None or not color_input.is_linked:
        return True
    return color_input.links[0].from_node.bl_idname != "ShaderNodeTexImage"


def _needs_bake(material: Optional[bpy.types.Material]) -> bool:
    if material is None:
        return False
    principled = _find_principled(material)
    if principled is None:
        return False
    return (
        _needs_factor_bake(principled.inputs.get("Base Color"))
        or _needs_factor_bake(principled.inputs.get("Roughness"))
        or _needs_normal_bake(principled.inputs.get("Normal"))
    )


def _new_bake_image(name: str, colorspace: str) -> bpy.types.Image:
    image = bpy.data.images.new(name, _BAKE_SIZE, _BAKE_SIZE)
    image.colorspace_settings.name = colorspace
    return image


def _activate_bake_target(material: bpy.types.Material, image: bpy.types.Image) -> None:
    """Every bake pass reads/writes whichever Image Texture node is the
    node tree's own active node — same node is reused (re-pointed at a fresh
    image) across this material's own multiple passes, one call each."""
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
    image = _new_bake_image(image_name, colorspace)
    _activate_bake_target(material, image)
    if pass_filter:
        bpy.ops.object.bake(type=bake_type, pass_filter=pass_filter, margin=4)
    else:
        bpy.ops.object.bake(type=bake_type, margin=4)
    image_node = material.node_tree.nodes.active
    # The graph that used to feed this input is now baked into `image` —
    # replace it with the baked texture so the exporter sees a plain,
    # representable Image Texture, not the original (still-present-on-
    # `material`, now-orphaned) node graph.
    material.node_tree.links.new(image_node.outputs["Color"], principled.inputs[input_name])


def _bake_normal_channel(
    material: bpy.types.Material,
    principled: bpy.types.ShaderNodeBsdfPrincipled,
    image_name: str,
) -> None:
    image = _new_bake_image(image_name, "Non-Color")
    _activate_bake_target(material, image)
    # Tangent space + R=+X/G=+Y/B=+Z (Blender's own real bl_rna defaults for
    # this operator, confirmed via introspection rather than assumed) is
    # exactly glTF's own normalTexture convention (OpenGL-style, Y+ up) — no
    # channel remap needed between Blender's bake and glTF's expectation.
    bpy.ops.object.bake(
        type="NORMAL",
        normal_space="TANGENT",
        normal_r="POS_X",
        normal_g="POS_Y",
        normal_b="POS_Z",
        margin=4,
    )
    image_node = material.node_tree.nodes.active
    # Raw Image Texture RGB (0..1) isn't a normal vector — a Normal Map node
    # is what decodes it back to tangent-space -1..1 for Principled's Normal
    # input, the same chain Blender's own glTF exporter already recognizes
    # natively for a real (non-baked) normal map.
    normal_map_node = material.node_tree.nodes.new("ShaderNodeNormalMap")
    normal_map_node.space = "TANGENT"
    material.node_tree.links.new(image_node.outputs["Color"], normal_map_node.inputs["Color"])
    material.node_tree.links.new(normal_map_node.outputs["Normal"], principled.inputs["Normal"])


def bake_procedural_channels(duplicate: bpy.types.Object) -> list:
    """Bakes every procedural Base Color/Roughness/Normal input into a fresh
    Image Texture, for every material slot on `duplicate` that needs it (see
    _needs_bake) — swapping in an independent material *copy* per slot.
    `duplicate` must already be the sole selected + active object
    (gltf_exporter.py's own export_object_glb sets this up).

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
        # omits/keeps whatever it already could, same as if this file didn't
        # exist) rather than fail the whole object's sync over one unbakeable
        # material.
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
            principled = _find_principled(new_material)

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

            baked_materials.append(new_material)
    finally:
        bpy.context.scene.render.engine = original_engine
        bpy.context.scene.cycles.samples = original_samples
        duplicate.active_material_index = original_active_index

    return baked_materials


def cleanup_baked_materials(materials: list) -> None:
    """Removes every material (and its baked image(s)) bake_procedural_channels()
    returned — call from export_object_glb's own finally block, same as its
    duplicate/duplicate_armature cleanup."""
    for material in materials:
        for node in material.node_tree.nodes:
            if node.bl_idname == "ShaderNodeTexImage" and node.image is not None:
                bpy.data.images.remove(node.image)
        bpy.data.materials.remove(material)


def cleanup_duplicate_mesh(mesh) -> None:
    """Removes a mesh-data copy bake_procedural_channels() made, once nothing
    still references it — call *after* the duplicate object itself has been
    removed (that drop is what brings this to 0 users; calling any earlier
    would fail). A no-op if `mesh` still has users (the fast path where
    bake_procedural_channels() never had to copy anything, or this same mesh
    is somehow still referenced elsewhere) — without this leaving an orphaned
    mesh datablock behind on every baked send, across a long-running Blender
    session sending many objects.

    Also a no-op for anything that isn't a real bpy.types.Mesh: both
    bake_procedural_channels() and approximate_volume_materials() only ever
    copy `.data` for a MESH object (each checks `duplicate.type != "MESH"`
    up front) — a CURVE/SURFACE/META/FONT object's `.data` is never copied,
    so it's still the real, live datablock the original scene object owns.
    `bpy.data.meshes.remove()` on one of those would be a type mismatch
    (wrong collection) even before considering it's not a duplicate at all."""
    if not isinstance(mesh, bpy.types.Mesh):
        return
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)
