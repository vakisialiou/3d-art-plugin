"""Max Texture for the user's own images: an image bigger than the scene's
limit is exported from a scaled-down copy, on a per-slot material copy, so
the user's images and materials never change. Bakes already come out at most
that size (web_settings.Snapshot.bake_size_for).
"""

import bpy

from .shader_bake import tag_bake_image


def _own_material(duplicate: bpy.types.Object, index: int, created: list) -> bpy.types.Material:
    """The slot's material as a copy only this export uses (made once)."""
    slot = duplicate.material_slots[index]
    material = slot.material
    if material in created:
        return material
    copy = material.copy()
    created.append(copy)
    if slot.link == "OBJECT":
        slot.material = copy
    else:
        if duplicate.data.users > 1:
            duplicate.data = duplicate.data.copy()
        duplicate.data.materials[index] = copy
    return copy


def _scaled(image: bpy.types.Image, max_size: int, cache: dict) -> bpy.types.Image:
    scaled = cache.get(image.name)
    if scaled is None:
        factor = max_size / max(image.size)
        scaled = image.copy()
        scaled.scale(max(1, round(image.size[0] * factor)), max(1, round(image.size[1] * factor)))
        tag_bake_image(scaled)
        cache[image.name] = scaled
    return scaled


def cap_textures(duplicate: bpy.types.Object, max_size: int, created: list) -> None:
    """Swaps every image above `max_size` (0 = no limit) for a scaled copy,
    on the duplicate's material copies. Images inside node groups are left
    alone: a group is shared with the user's other materials."""
    if not max_size or duplicate.type != "MESH":
        return
    cache: dict = {}
    for index, slot in enumerate(duplicate.material_slots):
        material = slot.material
        if material is None or material.node_tree is None:
            continue
        oversized = [
            node.name
            for node in material.node_tree.nodes
            if node.bl_idname == "ShaderNodeTexImage" and node.image is not None and max(node.image.size) > max_size
        ]
        if not oversized:
            continue
        own = _own_material(duplicate, index, created)
        for name in oversized:
            node = own.node_tree.nodes[name]
            node.image = _scaled(node.image, max_size, cache)
