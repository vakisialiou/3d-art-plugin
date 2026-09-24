import bpy

from .constants import DEV_TOKEN, SERVER_URL
from .project import get_project_id
from .socket_client import SocketIOEmitError, emit_once
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
        if describe_world_hdri_source(context) is None:
            cls.poll_message_set(
                "World has neither an Environment Texture image nor a Sky Texture to send"
            )
            return False
        return True

    def execute(self, context):
        project_id = get_project_id(context)
        if not project_id:
            self.report({"ERROR"}, "Set a Project ID in the 3D Art panel before sending")
            return {"CANCELLED"}

        payload = build_world_hdri_sync(context)
        if payload is None:
            self.report({"WARNING"}, "World has no Environment Texture image or Sky Texture to send")
            return {"CANCELLED"}

        try:
            emit_once(
                SERVER_URL,
                "blender-world-hdri-sync",
                payload,
                auth={"token": DEV_TOKEN, "projectId": project_id},
            )
        except SocketIOEmitError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        self.report({"INFO"}, "Sent HDRI to 3D Art")
        return {"FINISHED"}
