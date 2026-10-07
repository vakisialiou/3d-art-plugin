"""Shared Cycles-bake plumbing for material_bake.py, material_flatten.py and
material_volume.py (find_active_output() also serves world_sync.py).

find_principled_surface() walks from Material Output's Surface input — never
"the first Principled by type", which can pick a disconnected node or one half
of a Mix Shader. `None` means Surface isn't a single Principled BSDF
(material_flatten.py handles that).
"""

from contextlib import contextmanager
from typing import Optional

import bpy
import numpy as np

BAKE_SAMPLES = 16

# The resolution new_bake_image() uses; a Send sets it per object (bake_size()).
_bake_size = 512

# A bake whose sampled texels all sit within this of each other is one flat
# value: an 8-bit constant bakes to identical bytes, so this is about exact.
_FLAT_TOLERANCE = 0.6 / 255
# Points sampled per triangle for the flatness check, as barycentric weights.
_SAMPLE_WEIGHTS = np.array(
    [[1 / 3, 1 / 3, 1 / 3], [0.6, 0.2, 0.2], [0.2, 0.6, 0.2], [0.2, 0.2, 0.6]], dtype=np.float32
)
_MAX_SAMPLED_TRIANGLES = 50_000

# Marks the images new_bake_image() creates, so cleanup removes only those: a
# material.copy() shares the user's own Image datablocks, it doesn't copy them.
_BAKE_IMAGE_TAG = "skyray_bake"


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


@contextmanager
def bake_size(size: int):
    """Bakes inside use `size` × `size` images (the scene's Web Optimization)."""
    global _bake_size
    previous = _bake_size
    _bake_size = int(size)
    try:
        yield
    finally:
        _bake_size = previous


def new_bake_image(name: str, colorspace: str) -> bpy.types.Image:
    image = bpy.data.images.new(name, _bake_size, _bake_size)
    image.colorspace_settings.name = colorspace
    tag_bake_image(image)
    return image


def tag_bake_image(image: bpy.types.Image) -> None:
    """Marks an image the export made (a bake, a scaled copy) for cleanup."""
    image[_BAKE_IMAGE_TAG] = True


def is_bake_image(image: bpy.types.Image) -> bool:
    return bool(image.get(_BAKE_IMAGE_TAG))


def _srgb_to_linear(value: np.ndarray) -> np.ndarray:
    return np.where(value <= 0.04045, value / 12.92, ((value + 0.055) / 1.055) ** 2.4)


def flat_value(image: bpy.types.Image, mesh: bpy.types.Mesh) -> Optional[tuple]:
    """The one RGBA value (linear) a bake came out as, or None when it varies.

    Sampled where the mesh's faces land in UV space (texels outside the UV
    islands keep the empty image's color, so a whole-image check would never
    call a bake flat)."""
    uv_layer = mesh.uv_layers.active
    if uv_layer is None or not mesh.loop_triangles:
        return None
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape(height, width, 4)

    uvs = np.empty(len(uv_layer.data) * 2, dtype=np.float32)
    uv_layer.data.foreach_get("uv", uvs)
    uvs = uvs.reshape(-1, 2)
    corners = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("loops", corners)
    triangles = uvs[corners.reshape(-1, 3)][:_MAX_SAMPLED_TRIANGLES]  # (n, 3, 2)
    points = np.einsum("sk,nkd->nsd", _SAMPLE_WEIGHTS, triangles).reshape(-1, 2)
    columns = np.clip((np.mod(points[:, 0], 1.0) * width).astype(np.int32), 0, width - 1)
    rows = np.clip((np.mod(points[:, 1], 1.0) * height).astype(np.int32), 0, height - 1)
    samples = pixels[rows, columns]
    low, high = samples.min(axis=0), samples.max(axis=0)
    if float((high - low).max()) > _FLAT_TOLERANCE:
        return None
    value = (low + high) / 2
    if image.colorspace_settings.name == "sRGB":
        value[:3] = _srgb_to_linear(value[:3])
    return tuple(float(channel) for channel in value)


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


class coat_disabled:
    """Context manager: zeroes (and unlinks) Principled's Coat Weight for the
    bakes inside, restoring value and link (muted if it was) on exit, even if
    a bake raises.

    Cycles' bake passes don't isolate the base layer: NORMAL and ROUGHNESS
    average every BSDF closure, the coat included
    (surface_shader_average_normal/_roughness), and DIFFUSE COLOR / EMIT come
    out attenuated and tinted by the coat (principled_bsdf_emission's
    closure_layering_weight). The coat itself ships separately, as
    KHR_materials_clearcoat."""

    def __init__(self, principled: bpy.types.ShaderNodeBsdfPrincipled) -> None:
        self._principled = principled

    def __enter__(self) -> None:
        weight = self._principled.inputs["Coat Weight"]
        self._value = weight.default_value
        link = weight.links[0] if weight.is_linked else None
        self._from = link.from_socket if link is not None else None
        self._muted = link is not None and link.is_muted
        if link is not None:
            self._principled.id_data.links.remove(link)
        weight.default_value = 0.0

    def __exit__(self, *exc_info: object) -> None:
        weight = self._principled.inputs["Coat Weight"]
        weight.default_value = self._value
        if self._from is not None:
            self._principled.id_data.links.new(self._from, weight).is_muted = self._muted


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
