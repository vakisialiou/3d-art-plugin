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
from typing import Optional

import bpy
from mathutils import Matrix


def export_object_glb(obj: bpy.types.Object) -> bytes:
    """Exports `obj`'s geometry (plus skin + animation, if `obj` has an
    Armature modifier) at the origin — its actual placement is sent
    separately as explicit fields (see scene_graph.py) and applied on the
    browser side. This isn't optional: exporting an object standalone
    (without its parent in the selection), Blender's glTF exporter bakes the
    object's *world* transform onto the node — verified by decoding the
    exported node JSON directly. Leaving that in place would double-apply the
    transform on top of what scene_graph.py sends, compounding position and
    rotation.

    Exports temporary duplicates rather than touching `obj` (or its armature)
    itself — the originals' parenting/transform is never mutated, even
    momentarily, so a crash mid-export can't leave them disturbed. Duplicates
    share mesh/armature data (not a deep copy) so this stays cheap.

    If `obj` is skinned, the armature modifier's target object must be
    exported alongside it in the same call — exporting the mesh alone drops
    the skin binding silently (the Armature modifier's target was never in
    the export selection), and exporting the armature alone produces a skin
    with no mesh node referencing it. Both duplicates are reparented to each
    other (mirroring the real relationship) and the pair as a whole is reset
    to the origin, on the duplicate *armature* — the duplicate mesh keeps its
    real local-to-armature transform (`obj.matrix_local`) so the bind pose
    isn't altered, matching what Blender's own exporter expects.
    """
    # Snapshot selection before creating the duplicate: obj.copy() also copies
    # `obj`'s selected-state, so a snapshot taken after linking it could pick
    # the duplicate up as though it were part of the original selection.
    original_selection = list(bpy.context.selected_objects)
    original_active = bpy.context.view_layer.objects.active

    armature = _find_armature_target(obj)

    duplicate = obj.copy()
    duplicate_armature = None

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

    # Blender's glTF exporter determines root/parent nodes from the evaluated
    # depsgraph (tree.py's construct()), which doesn't pick up an in-script
    # reparent (duplicate.parent = duplicate_armature, above) until the view
    # layer is explicitly updated — without this, the exporter treats
    # `duplicate` as parentless and silently drops the skin. Verified by
    # decoding the exported glb with and without this call.
    bpy.context.view_layer.update()

    bpy.ops.object.select_all(action="DESELECT")
    duplicate.select_set(True)
    if duplicate_armature is not None:
        duplicate_armature.select_set(True)
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
                # Explicit, not left to the operator's own default: bakes the
                # armature's currently-assigned action only (not unrelated
                # NLA tracks/orphaned actions elsewhere in the file that
                # happen to be bone-compatible — the default ACTIONS mode
                # would pull those in too).
                export_animations=True,
                export_animation_mode="ACTIVE_ACTIONS",
            )
            with open(glb_path, "rb") as glb_file:
                return glb_file.read()
    finally:
        bpy.data.objects.remove(duplicate)
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
