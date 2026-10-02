"""Exports a single Blender object to a .glb via Blender's own glTF exporter —
geometry + materials only; scene_graph.py sends the transform.

export_yup=False breaks the glTF spec on purpose: only our own GLTFLoader reads
this file, and 3d-art-web's scene is Z-up like Blender (THREE.Object3D.DEFAULT_UP
in render.worker.ts), so there is no axis conversion anywhere in the pipeline.

Textures keep their original resolution — slow sends of heavy scenes are
accepted, never worked around by downscaling.
"""

import os
import tempfile
from typing import Optional

import bpy
from mathutils import Matrix

from .material_bake import (
    bake_procedural_channels,
    cleanup_baked_materials,
    cleanup_duplicate_mesh,
)
from .material_flatten import flatten_incompatible_surfaces
from .material_volume import approximate_volume_materials


def export_object_glb(obj: bpy.types.Object) -> bytes:
    """Exports `obj` (plus skin + animation, if it has an Armature modifier)
    at the origin, via temporary duplicates so the originals are never
    mutated. Duplicates share mesh/armature data, so this stays cheap.

    The origin reset is required: a standalone export bakes the object's
    *world* transform onto the glTF node, which would double-apply on top of
    scene_graph.py's transform.

    A skinned mesh must be exported together with its armature target, or
    the skin binding is dropped silently. The duplicate pair is reparented
    and the reset applies to the armature; the mesh keeps `obj.matrix_local`
    so the bind pose is unchanged.
    """
    # Snapshot before obj.copy(): the copy inherits obj's selected state and
    # would otherwise be restored as part of the original selection.
    original_selection = list(bpy.context.selected_objects)
    original_active = bpy.context.view_layer.objects.active

    armature = _find_armature_target(obj)

    duplicate = obj.copy()
    duplicate_armature = None
    # Each preprocessing step appends a material the moment it creates it, so
    # cleanup also covers a step that raised partway through.
    preprocessed_materials = []

    try:
        if armature is not None:
            duplicate_armature = armature.copy()
            duplicate_armature.parent = None
            duplicate_armature.matrix_basis = Matrix.Identity(4)
            bpy.context.collection.objects.link(duplicate_armature)

            for modifier in duplicate.modifiers:
                if modifier.type == "ARMATURE" and modifier.object == armature:
                    modifier.object = duplicate_armature

            duplicate.parent = duplicate_armature
            duplicate.matrix_parent_inverse = Matrix.Identity(4)
            duplicate.matrix_basis = obj.matrix_local
        else:
            duplicate.parent = None
            duplicate.matrix_basis = Matrix.Identity(4)

        bpy.context.collection.objects.link(duplicate)

        # The exporter reads parenting from the evaluated depsgraph (tree.py's
        # construct()), which misses the in-script reparent above until the
        # view layer updates — otherwise the skin is dropped silently.
        bpy.context.view_layer.update()

        bpy.ops.object.select_all(action="DESELECT")
        duplicate.select_set(True)
        bpy.context.view_layer.objects.active = duplicate

        # Needs `duplicate` as the sole selected+active object (bake requires
        # both, and rejects a selected non-mesh such as the armature). Order
        # matters: flatten first turns a non-Principled Surface (e.g. a Mix
        # Shader) into one Principled for bake to work on.
        flatten_incompatible_surfaces(duplicate, preprocessed_materials)
        bake_procedural_channels(duplicate, preprocessed_materials)
        approximate_volume_materials(duplicate, preprocessed_materials)

        if duplicate_armature is not None:
            duplicate_armature.select_set(True)

        with tempfile.TemporaryDirectory() as tmp_dir:
            glb_path = os.path.join(tmp_dir, "object.glb")
            bpy.ops.export_scene.gltf(
                filepath=glb_path,
                export_format="GLB",
                use_selection=True,
                export_apply=True,
                export_yup=False,
                # Only the armature's assigned action; the default ACTIONS
                # mode also pulls in any bone-compatible action in the file.
                export_animations=True,
                export_animation_mode="ACTIVE_ACTIONS",
            )
            with open(glb_path, "rb") as glb_file:
                return glb_file.read()
    finally:
        cleanup_baked_materials(preprocessed_materials)
        # Read only now: any preprocessing step may have swapped
        # duplicate.data for an independent copy, even one that then raised.
        duplicate_mesh_data = duplicate.data
        bpy.data.objects.remove(duplicate)
        cleanup_duplicate_mesh(duplicate_mesh_data)
        if duplicate_armature is not None:
            bpy.data.objects.remove(duplicate_armature)
        bpy.ops.object.select_all(action="DESELECT")
        for selected in original_selection:
            selected.select_set(True)
        bpy.context.view_layer.objects.active = original_active


def _find_armature_target(obj: bpy.types.Object) -> Optional[bpy.types.Object]:
    for modifier in obj.modifiers:
        if modifier.type == "ARMATURE" and modifier.object is not None:
            return modifier.object
    return None
