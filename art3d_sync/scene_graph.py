"""Walks the Blender scene graph and builds the blender-sync `objects[]`
payload — one entry per object, geometry as its own small .glb, transform as
explicit local-to-parent fields so the browser can resolve hierarchy by id.
"""

import base64
from typing import Callable, Optional

import bpy

from .gltf_exporter import export_object_glb
from .object_id import resolve_stable_ids

# matrix_local is sent as-is: the web scene is Z-up like Blender, no axis
# conversion (see gltf_exporter.py).

# Types the glTF exporter (export_apply=True) evaluates to a mesh. The rest
# have no geometry (EMPTY/ARMATURE/LATTICE/LIGHT_PROBE/SPEAKER), sync on their
# own channel (CAMERA/LIGHT), or don't convert (GREASEPENCIL/VOLUME/POINTCLOUD/
# CURVES).
_MESH_CONVERTIBLE_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}


def collect_selected_with_ancestors(context: bpy.types.Context) -> list:
    collected: dict = {}
    for obj in context.selected_objects:
        _add_with_ancestors(obj, collected)
    return list(collected.values())


def collect_all_scene_objects(context: bpy.types.Context) -> list:
    return list(context.scene.objects)


def _add_with_ancestors(obj: bpy.types.Object, collected: dict) -> None:
    if obj.name in collected:
        return
    collected[obj.name] = obj
    if obj.parent is not None:
        _add_with_ancestors(obj.parent, collected)


def build_sync_objects(
    objects: list,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> list:
    included_names = {obj.name for obj in objects}
    resolved_ids = resolve_stable_ids(objects)
    payload_objects = []

    for index, obj in enumerate(objects):
        if on_progress is not None:
            on_progress(index, len(objects))

        parent_included = obj.parent is not None and obj.parent.name in included_names
        location, rotation, scale = obj.matrix_local.decompose()

        payload_objects.append(
            {
                "id": resolved_ids[obj.name],
                # Display-only — may change between syncs, never used as a key.
                "name": obj.name,
                "parentId": resolved_ids[obj.parent.name] if parent_included else None,
                "action": "update",
                # Blender's Object.type enum (rna_enum_object_type_items,
                # rna_object.cc), sent verbatim.
                "type": obj.type,
                "position": [location.x, location.y, location.z],
                # Quaternion, not Euler: Euler order names ("XYZ" etc.) differ in
                # meaning between mathutils and three.js; quaternions don't.
                "rotation": [rotation.x, rotation.y, rotation.z, rotation.w],
                "scale": [scale.x, scale.y, scale.z],
                "glb": _export_glb_base64(obj) if obj.type in _MESH_CONVERTIBLE_TYPES else None,
            }
        )

    return payload_objects


def _export_glb_base64(obj: bpy.types.Object) -> str:
    return base64.b64encode(export_object_glb(obj)).decode("ascii")


def build_delete_entries(deleted_ids: set) -> list:
    return [{"id": object_id, "action": "delete"} for object_id in deleted_ids]
