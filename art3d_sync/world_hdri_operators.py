import bpy

from . import upload
from .world_hdri_sync import build_world_hdri_sync, describe_world_hdri_source


class ART3D_OT_send_world_hdri(bpy.types.Operator):
    bl_idname = "art3d.send_world_hdri"
    bl_label = "Send HDRI"
    bl_description = (
        "Sends the World's Environment Texture image if one is assigned, otherwise "
        "bakes the procedural Sky Texture into an equirectangular HDRI — for Material Preview"
    )

    @classmethod
    def poll(cls, context):
        if not upload.can_send(cls, context):
            return False
        if describe_world_hdri_source(context) is None:
            cls.poll_message_set(
                "World has neither an Environment Texture image nor a Sky Texture to send"
            )
            return False
        return True

    def execute(self, context):
        if describe_world_hdri_source(context) is None:
            self.report({"WARNING"}, "World has no Environment Texture image or Sky Texture to send")
            return {"CANCELLED"}

        payload = upload.send(self, context, "blender-world-hdri-sync", lambda _progress: build_world_hdri_sync(context))
        if payload is None:
            return {"CANCELLED"}
        self.report({"INFO"}, "Sent HDRI to 3D Art")
        return {"FINISHED"}
