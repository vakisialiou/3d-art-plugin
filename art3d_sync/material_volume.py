"""Approximates a Blender volume shader (Volume Scatter / Volume Absorption /
Principled Volume) for glTF export — glTF has no volume representation at
all, and Blender's own glTF exporter completely ignores Material Output's
Volume socket (confirmed by reading
io_scene_gltf2/blender/exp/material/pbr_metallic_roughness.py: it only ever
reads the Surface socket's own Base Color/Alpha/etc).

Two real cases, detected generically (never by material name):

1. The Volume shader sits alongside a Surface Principled BSDF that has real
   Transmission Weight (materials-demo.blend's Mat_Air/Mat_Cloud: Cycles
   renders these as a transmissive/refractive solid — Surface and Volume
   working *together*, confirmed by a real Cycles render, not a fluffy
   translucent haze). Left alone, Blender's exporter already reads that
   Surface correctly via the standard glTF extension
   KHR_materials_transmission (search_node_tree.py's export_transmission
   reads the Principled BSDF's own Transmission Weight socket directly,
   unconditionally) — so the Surface needs no changes at all. What's
   missing is the Volume's own contribution (its Color/Density), which has
   no representation unless the material also carries a
   KHR_materials_volume extension. Blender's real, intended mechanism for
   that (confirmed via io_scene_gltf2/blender/exp/material/extensions/volume.py
   and .../com/material_helpers.py, not guessed): a disconnected "glTF
   Material Output" node group carrying a Thickness value, plus a
   ShaderNodeVolumeAbsorption node carrying Color/Density — both purely for
   the exporter to find, ignored by Cycles. This is the officially
   documented way Blender users attach glTF-only volume data to a material,
   not a workaround. Both KHR_materials_transmission and KHR_materials_volume
   are natively supported on the read side too (three.js's GLTFLoader maps
   them straight onto MeshPhysicalMaterial), so this path needs zero
   web-side code.

2. The Volume shader has no meaningfully-transmissive Surface alongside it
   (Transmission Weight ~0 or absent) — a "pure fog" material with nothing
   for KHR_materials_transmission to attach to. Falls back to a flat,
   single-shell alpha-blend approximation built from the volume's own
   Density (Beer-Lambert: alpha = 1 - exp(-density * thickness), thickness
   = the real object's own bounding size, not a fixed guess) — cruder, but
   at least reads as haze instead of nothing. No real material in this
   project's reference scene exercises this path today; kept because
   "volume shader with an inert/absent surface" is a legitimate, generic
   case, not a hypothetical to special-case away.

Mapping detail for the KHR_materials_volume nodes:
- Thickness <- the volume node's own Density input. Flat Density becomes a
  flat Thickness factor (the object's own bounding size — Thickness is a
  geometric quantity, independent of Density; Density instead drives
  attenuationDistance below). A *procedural* Density (materials-demo.blend's
  Mat_Cloud: noise-driven) has no per-pixel equivalent in
  attenuationDistance (a single glTF factor) but glTF's thicknessTexture
  *is* spatial — so the same raw baked density map (no Beer-Lambert curve;
  raw density is already the right unit for "how deep is the medium here")
  is reused as the thickness texture, reproducing the internal density
  variation as spatially-varying depth instead of losing it.
- attenuationDistance <- 1 / density (Beer-Lambert distance-to-37%), using a
  flat Density value, or the mean of a baked/procedural one — Blender's own
  export_volume.py computes this exact same reciprocal from a *constant*
  Density socket, confirming this mapping rather than inventing it.
- attenuationColor <- the volume node's own Color input (its scattering
  tint) for both Volume Scatter and Principled Volume — both real node
  types expose a "Color" input, checked via bpy introspection, not memory.
- Principled Volume's separate Absorption Color and Anisotropy are
  deliberately NOT folded in: this project's reference scene's own real
  Absorption Color value is (0,0,0) — pure black — and glTF's
  attenuationColor already carries the material's color story; combining a
  second, differently-scoped color input on a guess risks corrupting color
  on some future material for no verified gain. Anisotropy has no
  glTF/three.js equivalent at all. Emission Color/Strength, where present
  (Principled Volume only), pass straight through onto the Surface
  Principled BSDF's own Emission inputs (glTF's native emissiveFactor).

Baking an arbitrary node socket (Density, Color) has no dedicated Blender
bake type — same gap material_bake.py's docstring flagged for Metallic.
Exercised here via the same technique it names: temporarily rewire the
socket into an Emission shader's Color input (Blender implicitly broadcasts
a scalar into a color input as R=G=B, confirmed empirically) wired to
Material Output's Surface, then bake type='EMIT'.
"""

import math
from array import array
from typing import Optional

import bpy

_VOLUME_NODE_TYPES = {
    "ShaderNodeVolumeScatter",
    "ShaderNodeVolumeAbsorption",
    "ShaderNodeVolumePrincipled",
}

_BAKE_SIZE = 512
_BAKE_IMAGE_PREFIX = "__art3d_volume"
# Same reasoning as material_bake.py's _BAKE_SAMPLES: reading a node graph's
# own values, not the scene's real light transport — a low, fixed sample
# count keeps export fast without under-sampling anything that matters.
_BAKE_SAMPLES = 16

# Below this, a Surface's Transmission Weight isn't a real authored glass
# effect worth preserving via KHR_materials_transmission — falls back to the
# flat alpha-blend approximation instead.
_TRANSMISSION_EPSILON = 0.001

# Blender's own real name for its glTF-only-properties node group (confirmed
# via io_scene_gltf2/blender/com/material_helpers.py's get_gltf_node_name())
# — the exporter matches a ShaderNodeGroup by this node_tree name prefix,
# case-insensitively, regardless of which material or .blend it lives in.
_GLTF_SETTINGS_GROUP_NAME = "glTF Material Output"


def _find_output(material: bpy.types.Material) -> Optional[bpy.types.ShaderNodeOutputMaterial]:
    output = None
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeOutputMaterial":
            if node.is_active_output:
                return node
            if output is None:
                output = node
    return output


def find_volume_node(material: Optional[bpy.types.Material]):
    if material is None or not material.use_nodes or material.node_tree is None:
        return None
    output = _find_output(material)
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


def _find_principled_surface(material: bpy.types.Material):
    output = _find_output(material)
    if output is None:
        return None
    surface = output.inputs.get("Surface")
    if surface is None or not surface.is_linked:
        return None
    node = surface.links[0].from_node
    if node.bl_idname != "ShaderNodeBsdfPrincipled":
        return None
    return node


def _has_real_transmission(material: bpy.types.Material) -> bool:
    surface = _find_principled_surface(material)
    if surface is None:
        return False
    transmission = surface.inputs.get("Transmission Weight")
    if transmission is None:
        return False
    if transmission.is_linked:
        return True
    return transmission.default_value > _TRANSMISSION_EPSILON


def _bake_socket_to_image_node(
    material: bpy.types.Material,
    output_socket,
    image_name: str,
    colorspace: str,
) -> bpy.types.ShaderNodeTexImage:
    """Bakes `output_socket`'s resolved value (color or scalar, broadcast
    across RGB) into a fresh image, via a temporary Emission shader wired to
    Material Output's Surface. Restores whatever Surface pointed to before
    this call once done — the real Surface Principled BSDF (see module
    docstring: this path never replaces or disconnects it)."""
    tree = material.node_tree
    output = _find_output(material)
    surface_input = output.inputs["Surface"]
    original_from = surface_input.links[0].from_socket if surface_input.is_linked else None

    emission = tree.nodes.new("ShaderNodeEmission")
    tree.links.new(output_socket, emission.inputs["Color"])
    tree.links.new(emission.outputs["Emission"], surface_input)

    image = bpy.data.images.new(image_name, _BAKE_SIZE, _BAKE_SIZE)
    image.colorspace_settings.name = colorspace
    image_node = tree.nodes.new("ShaderNodeTexImage")
    image_node.image = image
    tree.nodes.active = image_node

    original_engine = bpy.context.scene.render.engine
    original_samples = bpy.context.scene.cycles.samples
    bpy.context.scene.render.engine = "CYCLES"
    bpy.context.scene.cycles.samples = _BAKE_SAMPLES
    try:
        bpy.ops.object.bake(type="EMIT", margin=4)
    finally:
        bpy.context.scene.render.engine = original_engine
        bpy.context.scene.cycles.samples = original_samples

    tree.nodes.remove(emission)
    tree.links.new(original_from, surface_input)

    return image_node


def _resolve_channel(material: bpy.types.Material, socket, image_name: str, colorspace: str):
    """Returns ('factor', value) for a flat/unlinked socket (value is a
    float or an RGBA tuple, whatever default_value already is), or
    ('image', image_node) if it's graph-driven — reusing the graph's own
    Image Texture node directly when that's literally all it is (same
    shortcut material_bake.py uses), baking everything else."""
    if socket is None:
        return 'factor', None
    if not socket.is_linked:
        value = socket.default_value
        return 'factor', tuple(value) if hasattr(value, '__len__') else value
    from_node = socket.links[0].from_node
    if from_node.bl_idname == "ShaderNodeTexImage":
        return 'image', from_node
    return 'image', _bake_socket_to_image_node(material, socket.links[0].from_socket, image_name, colorspace)


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
    """Mirrors io_scene_gltf2's own create_settings_group() (material_helpers.py)
    closely enough to matter: BlenderMaterialIndentifier.__can_use_inline()
    (materials.py) only checks for an *Occlusion* socket to decide whether a
    material uses the glTF settings node at all — not Thickness. Omitting
    Occlusion here (confirmed by testing: it silently passed with only
    Thickness present) makes the exporter take its "inline shader nodes"
    fast path instead, which flattens the live shading graph and drops any
    disconnected node — including the Thickness group and the
    ShaderNodeVolumeAbsorption node this module adds, with no error, just a
    silently missing KHR_materials_volume. The Occlusion socket itself is
    otherwise unused here."""
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
    """Attaches the disconnected node pair Blender's own exporter looks for
    (see module docstring) so KHR_materials_volume gets exported alongside
    the Surface's already-correct KHR_materials_transmission. Never touches
    the real Surface Principled BSDF."""
    tree = material.node_tree
    output = _find_output(material)
    vol_node = find_volume_node(material)

    settings_node = tree.nodes.new("ShaderNodeGroup")
    settings_node.node_tree = _get_or_create_gltf_settings_group()

    density_socket = vol_node.inputs.get("Density")
    density_kind, density_value = _resolve_channel(
        material, density_socket, f"{image_prefix}_density", "Non-Color",
    )

    absorption = tree.nodes.new("ShaderNodeVolumeAbsorption")
    if density_kind == 'image':
        # Spatial density variation has no equivalent in
        # KHR_materials_volume's single attenuationDistance factor —
        # represent it as a thicknessTexture instead (glTF: "thickness of
        # the volume beneath the surface" IS spatial), reusing the same
        # baked map so the internal variation isn't lost.
        # thicknessTexture values are 0..1, scaled by thicknessFactor
        # (export_volume.py's get_factor_from_socket only detects a
        # multiply-by-constant *before* the texture, defaulting to 1.0
        # otherwise) — insert that multiply explicitly so a 2m object
        # reports up to 2m of thickness, not an implicit 0..1m regardless of
        # real scale.
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
        # attenuationColor has no texture slot in KHR_materials_volume —
        # fall back to its baked average rather than leaving Blender's
        # neutral-white default in place.
        r = _image_mean_channel(color_value.image, 0)
        g = _image_mean_channel(color_value.image, 1)
        b = _image_mean_channel(color_value.image, 2)
        absorption.inputs["Color"].default_value = (r, g, b, 1.0)
    else:
        _apply_channel(tree, absorption.inputs["Color"], color_kind, color_value)

    # get_socket(..., volume=True) (io_scene_gltf2's real exporter) only
    # finds a ShaderNodeVolumeAbsorption that's actually linked to the active
    # Material Output's Volume input — confirmed by reading
    # check_if_is_linked_to_active_output's use in get_node_socket, not
    # assumed. Safe to steal that link from the real volume node here: this
    # is a throwaway export-time material copy, never the live one Cycles
    # renders (see gltf_exporter.py's export_object_glb, which always
    # operates on a duplicate and discards it after export).
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

    surface = _find_principled_surface(material)
    if surface is None:
        return
    tree = material.node_tree
    _apply_channel(tree, surface.inputs["Emission Strength"], strength_kind, strength_value)
    color_kind, color_value = _resolve_channel(
        material, vol_node.inputs.get("Emission Color"), f"{image_prefix}_emitcolor", "sRGB",
    )
    _apply_channel(tree, surface.inputs["Emission Color"], color_kind, color_value)


def _apply_beer_lambert(image: bpy.types.Image, thickness: float) -> None:
    """Turns a baked raw-density image (R=G=B=density, see
    _bake_socket_to_image_node) into an alpha image in place: alpha = 1 -
    exp(-density * thickness). `thickness` is the real object's own bounding
    size, so this holds up for any future volume object regardless of
    scale — not a fixed guess."""
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
    image_node = _bake_socket_to_image_node(material, density_socket.links[0].from_socket, image_name, "Non-Color")
    _apply_beer_lambert(image_node.image, thickness)
    return 'image', image_node


def _build_flat_alpha_approximation(material: bpy.types.Material, thickness: float, image_prefix: str) -> None:
    """Fallback for a volume shader with no meaningfully-transmissive
    Surface alongside it (see module docstring, case 2) — no real material
    in this project's reference scene exercises this today."""
    tree = material.node_tree
    output = _find_output(material)
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
    """For every material slot on `duplicate` whose material has a real
    Blender volume shader (see is_volume_material), adds whatever glTF needs
    to represent it (see module docstring for the two cases). `duplicate`
    must already be the sole selected+active object (gltf_exporter.py's own
    export_object_glb sets this up, same precondition bake_procedural_channels
    relies on).

    Copies `duplicate.data` to an independent datablock the first time any
    slot actually needs this — checked via `.users > 1` rather than a shared
    flag with bake_procedural_channels, so this stays correct regardless of
    which of the two runs first (users == 1 already means whichever ran
    first made it independent). Objects with no volume materials pay
    nothing extra, same discipline as bake_procedural_channels.

    Returns the list of newly created material copies, for
    cleanup_baked_materials() (material_bake.py — same shape: an image per
    ShaderNodeTexImage node plus the material itself) to remove after
    export.
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
