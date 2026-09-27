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
  One of them (Mat_Titanium_Anodized, Layer Weight -> Color Ramp -> Base
  Color, a view-angle iridescence look) needs a different bake technique
  than the rest — see `_has_view_dependent_node`'s own doc comment.
- Normal: the dominant case — most materials feed a Bump node from a
  procedural texture (Wave/Noise/Voronoi/Checker/Mix), which has no glTF
  equivalent at all; a few feed a real Normal Map node instead, which *is*
  natively exportable as long as its own Color input is a plain Image
  Texture (the standard Blender-to-glTF normal-map workflow) — only the
  procedural cases need baking.
- Roughness: 2 materials (a Color Ramp, a Map Range).
- Emission: 2 materials (Mat_Lava, Mat_Hologram) drive Emission Strength
  through a procedural graph (their actual glow pattern — cracks/dithering)
  while Emission Color stays flat. glTF only has a texture slot on Emission
  *Color* (confirmed by reading io_scene_gltf2's own
  `material/extensions/emission.py`: `export_emission_texture` only ever
  gathers a texture from the "Emissive" — i.e. Emission Color — socket;
  Emission Strength is read as a plain factor via `get_factor_from_socket`,
  never a texture) — so baking Emission Strength alone into its own image
  and wiring that into Emission Strength, the way Roughness does for its own
  input, would export as an inert, un-textured factor and lose the pattern
  all over again. Instead: `bpy.ops.object.bake(type='EMIT')`, confirmed
  empirically to read Principled BSDF's own real Emission Color*Strength
  product directly with the material completely unmodified (no rewiring
  needed at all — unlike material_volume.py's Density/Color bake, Emission
  *is* already part of Surface's own contribution to what 'EMIT' bakes), so
  one bake captures the true combined result regardless of which of the two
  inputs is procedural. The baked image is wired into Emission Color;
  Emission Strength is reset to a flat 1.0 (the bake already carries the
  full product) — see `_bake_emission_channel`.
- Metallic: every material in the reference scene has it flat. Deliberately
  NOT baked here — unlike Base Color/Roughness, Blender's own bake operator
  (bpy.ops.object.bake, confirmed via its real bl_rna `type` enum) has no
  dedicated Metallic pass; the only way to bake an arbitrary socket like this
  is rewiring it through a temporary Emission shader and baking type='EMIT',
  the same technique material_volume.py already uses for its own Volume
  sockets — untested here because nothing in this scene exercises it. Add it
  the same way as Roughness below if a real material ever needs it.
"""

from typing import Optional

import bpy

from .shader_bake import bake_socket_to_image_node, find_principled_surface

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


def _has_view_dependent_node(socket, seen: Optional[set] = None) -> bool:
    """True if `socket`'s upstream graph contains a Fresnel or Layer Weight
    node (Mat_Titanium_Anodized's own real Base Color graph: Layer Weight ->
    Color Ramp -> Base Color). Confirmed empirically, not guessed: baking
    this exact socket via `_bake_factor_channel`'s normal DIFFUSE+COLOR pass
    produces solid (0,0,0) — no camera ray exists during a texture bake for
    a view-angle-dependent node to evaluate against — while baking the same
    socket through `bake_socket_to_image_node`'s Emission-rewire trick
    (which evaluates the real, complete shader output) produces its real,
    correct gradient. `_bake_factor_channel` routes a socket like this
    through that trick instead of its normal bake-pass-type path."""
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
    """True if Emission Color or Emission Strength is graph-driven — either
    alone means the pair's combined product needs baking as one texture (see
    _bake_emission_channel and the module docstring's Emission section)."""
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
    socket = principled.inputs[input_name]
    if _has_view_dependent_node(socket):
        # See _has_view_dependent_node's own doc comment — this bake type's
        # normal DIFFUSE/ROUGHNESS pass can't resolve a Fresnel/Layer Weight
        # node and silently bakes it to solid black instead.
        image_node = bake_socket_to_image_node(
            material, socket.links[0].from_socket, image_name, colorspace
        )
    else:
        image = _new_bake_image(image_name, colorspace)
        _activate_bake_target(material, image)
        if pass_filter:
            bpy.ops.object.bake(type=bake_type, pass_filter=pass_filter, margin=4)
        else:
            bpy.ops.object.bake(type=bake_type, margin=4)
        # An unpacked bake result can read back blank once enough further
        # bpy.ops.object.bake calls happen before export ever reads it (this
        # material's own remaining channels, then the next material in the
        # batch) — confirmed empirically, see shader_bake.bake_socket_to_image_node's
        # own comment. Packing immediately makes it durable regardless.
        image.pack()
        image_node = material.node_tree.nodes.active
    # The graph that used to feed this input is now baked into the image —
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
    image.pack()  # see _bake_factor_channel's own comment
    image_node = material.node_tree.nodes.active
    # Raw Image Texture RGB (0..1) isn't a normal vector — a Normal Map node
    # is what decodes it back to tangent-space -1..1 for Principled's Normal
    # input, the same chain Blender's own glTF exporter already recognizes
    # natively for a real (non-baked) normal map.
    normal_map_node = material.node_tree.nodes.new("ShaderNodeNormalMap")
    normal_map_node.space = "TANGENT"
    material.node_tree.links.new(image_node.outputs["Color"], normal_map_node.inputs["Color"])
    material.node_tree.links.new(normal_map_node.outputs["Normal"], principled.inputs["Normal"])


def _bake_emission_channel(
    material: bpy.types.Material,
    principled: bpy.types.ShaderNodeBsdfPrincipled,
    image_name: str,
) -> None:
    """See the module docstring's Emission section for why this bakes the
    combined Color*Strength product (not Strength alone) and why no node
    rewiring is needed first: `type='EMIT'` already reads Principled BSDF's
    own real Emission contribution directly off the material as-is."""
    image = _new_bake_image(image_name, "sRGB")
    _activate_bake_target(material, image)
    bpy.ops.object.bake(type="EMIT", margin=4)
    image.pack()  # see _bake_factor_channel's own comment
    image_node = material.node_tree.nodes.active
    material.node_tree.links.new(image_node.outputs["Color"], principled.inputs["Emission Color"])
    # The bake already carries the full Color*Strength product — a `.links`
    # entry left in place here would still resolve to its own graph's value
    # at export time (`default_value` alone is ignored while a socket stays
    # linked), double-applying the strength on top of the already-correct
    # baked texture.
    strength_input = principled.inputs["Emission Strength"]
    if strength_input.is_linked:
        material.node_tree.links.remove(strength_input.links[0])
    strength_input.default_value = 1.0


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
