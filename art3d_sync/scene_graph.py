"""Walks the Blender scene graph and builds the blender-sync `objects[]`
payload — one entry per object, geometry as its own small .glb, transform as
explicit local-to-parent fields so the browser can resolve hierarchy by id.
"""

import base64
from typing import Callable, Optional

import bpy

from .gltf_exporter import export_object_glb
from .object_id import get_stable_id

# No Z-up/Y-up conversion here (or anywhere in this pipeline) — 3d-art-web's
# whole scene is Z-up too (THREE.Object3D.DEFAULT_UP, see render.worker.ts),
# matching Blender natively. Blender's own matrix_local is sent as-is.


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
    payload_objects = []

    for index, obj in enumerate(objects):
        if on_progress is not None:
            on_progress(index, len(objects))

        parent_included = obj.parent is not None and obj.parent.name in included_names
        location, rotation, scale = obj.matrix_local.decompose()

        payload_objects.append(
            {
                "id": get_stable_id(obj),
                # Display-only — may change between syncs, never used as a key.
                "name": obj.name,
                "parentId": get_stable_id(obj.parent) if parent_included else None,
                "action": "update",
                # Blender's real Object.type enum (rna_enum_object_type_items,
                # source/blender/makesrna/intern/rna_object.cc) — sent verbatim,
                # not translated. Drives the object-tree icon on the browser
                # side (ui-kit/components/tree/icons), one real Blender
                # outliner icon per real type value.
                "type": obj.type,
                "position": [location.x, location.y, location.z],
                # Quaternion, not Euler: axis order ("XYZ" etc.) isn't guaranteed to mean
                # the same thing in Blender's mathutils vs three.js — quaternions have no
                # such ambiguity, and both compose with the same Hamilton product.
                "rotation": [rotation.x, rotation.y, rotation.z, rotation.w],
                "scale": [scale.x, scale.y, scale.z],
                "glb": _export_glb_base64(obj) if obj.type == "MESH" else None,
            }
        )

    return payload_objects


def _export_glb_base64(obj: bpy.types.Object) -> str:
    return base64.b64encode(export_object_glb(obj)).decode("ascii")
