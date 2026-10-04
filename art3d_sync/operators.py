import time

import bpy

from . import upload
from .object_id import get_existing_id
from .scene_graph import (
    build_delete_entries,
    build_sync_objects,
    collect_all_scene_objects,
    collect_selected_with_ancestors,
)
from .sent_ids import get_previous_sent_ids, set_sent_ids

_send_count = 0


class ART3D_OT_send_scene(bpy.types.Operator):
    bl_idname = "art3d.send_scene"
    bl_label = "Send to 3D Art"
    bl_description = "Exports objects to glTF (geometry + materials) and sends them to 3d-art-api"

    scope: bpy.props.EnumProperty(
        items=[
            ("selected", "Selected", "Send the selected objects, plus their ancestors (for hierarchy)"),
            ("all", "All", "Send every object in the scene"),
        ],
        default="selected",
    )

    @classmethod
    def poll(cls, context):
        return upload.can_send(cls, context)

    def execute(self, context):
        scene = context.scene
        objects = (
            collect_selected_with_ancestors(context)
            if self.scope == "selected"
            else collect_all_scene_objects(context)
        )

        # Deletion is scene-wide, independent of the Selected/All scope.
        current_scene_ids = {
            existing_id for obj in scene.objects if (existing_id := get_existing_id(obj)) is not None
        }
        previous_sent_ids = get_previous_sent_ids(scene)
        deleted_ids = previous_sent_ids - current_scene_ids
        delete_entries = build_delete_entries(deleted_ids)

        if not objects and not delete_entries:
            message = "Nothing to send — select an object first" if self.scope == "selected" else "Scene is empty"
            self.report({"WARNING"}, message)
            return {"CANCELLED"}

        window_manager = context.window_manager

        def build(progress):
            global _send_count

            def on_progress(done, _total):
                window_manager.progress_update(done)
                progress(done)

            window_manager.progress_begin(0, len(objects))
            try:
                payload_objects = build_sync_objects(objects, on_progress=on_progress)
            finally:
                window_manager.progress_end()
            payload_objects.extend(delete_entries)
            _send_count += 1
            return {
                "blenderVersion": _send_count,
                "timestamp": int(time.time() * 1000),
                "objects": payload_objects,
            }

        payload = upload.send(self, context, "blender-sync", build, total=len(objects))
        if payload is None:
            return {"CANCELLED"}

        payload_objects = payload["objects"]
        updated_ids = {entry["id"] for entry in payload_objects if entry["action"] == "update"}
        set_sent_ids(scene, (previous_sent_ids - deleted_ids) | updated_ids)

        sent_count = len(payload_objects) - len(delete_entries)
        if delete_entries:
            self.report(
                {"INFO"},
                f"Sent {sent_count} object(s), {len(delete_entries)} deletion(s) to 3D Art",
            )
        else:
            self.report({"INFO"}, f"Sent {sent_count} object(s) to 3D Art")
        return {"FINISHED"}
