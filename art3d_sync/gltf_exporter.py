"""Exports a single Blender object to a .glb via Blender's own glTF exporter.

Geometry + materials only — position/rotation/scale is computed separately in
scene_graph.py (local-to-parent, so hierarchy resolves correctly on the
browser side). Using the real exporter gets correct multi-material/per-face
splitting and modifier baking for free.

export_yup=False is deliberate: the glTF spec mandates Y-up, but we're not
interoperating with anything else that reads this file — only our own
GLTFLoader does. Keeping Blender's native Z-up numbers means 3d-art-web's
whole scene is Z-up too (THREE.Object3D.DEFAULT_UP, see render.worker.ts),
so there is no axis conversion anywhere in this pipeline. See CLAUDE.md.

Textures export at their original resolution — no downscaling. Heavy scenes
take longer to send; that's expected and fine (see CLAUDE.md), not something
to silently work around.
"""

import os
import tempfile

import bpy
from mathutils import Matrix


def export_object_glb(obj: bpy.types.Object) -> bytes:
    """Exports `obj`'s geometry only, at the origin — its actual placement is
    sent separately as explicit fields (see scene_graph.py) and applied on the
    browser side. This isn't optional: exporting an object standalone (without
    its parent in the selection), Blender's glTF exporter bakes the object's
    *world* transform onto the node — verified by decoding the exported node
    JSON directly. Leaving that in place would double-apply the transform on
    top of what scene_graph.py sends, compounding position and rotation.

    Exports a temporary unparented, transform-reset duplicate rather than
    touching `obj` itself — the original object's parenting/transform is never
    mutated, even momentarily, so a crash mid-export can't leave it disturbed.
    The duplicate shares mesh data (not a deep copy) so this stays cheap.
    """
    # Snapshot selection before creating the duplicate: obj.copy() also copies
    # `obj`'s selected-state, so a snapshot taken after linking it could pick
    # the duplicate up as though it were part of the original selection.
    original_selection = list(bpy.context.selected_objects)
    original_active = bpy.context.view_layer.objects.active

    duplicate = obj.copy()
    duplicate.parent = None
    duplicate.matrix_basis = Matrix.Identity(4)
    bpy.context.collection.objects.link(duplicate)

    bpy.ops.object.select_all(action="DESELECT")
    duplicate.select_set(True)
    bpy.context.view_layer.objects.active = duplicate

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            glb_path = os.path.join(tmp_dir, "object.glb")
            bpy.ops.export_scene.gltf(
                filepath=glb_path,
                export_format="GLB",
                use_selection=True,
                export_apply=True,
                export_yup=False,
            )
            with open(glb_path, "rb") as glb_file:
                return glb_file.read()
    finally:
        bpy.data.objects.remove(duplicate)
        bpy.ops.object.select_all(action="DESELECT")
        for selected in original_selection:
            selected.select_set(True)
        bpy.context.view_layer.objects.active = original_active
