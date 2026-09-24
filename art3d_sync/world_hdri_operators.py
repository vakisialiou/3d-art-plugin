import bpy

from .constants import DEV_TOKEN, SERVER_URL
from .project import get_project_id
from .socket_client import SocketIOEmitError, emit_once
from .world_hdri_sync import build_world_hdri_sync


class ART3D_OT_send_world_hdri(bpy.types.Operator):
    bl_idname = "art3d.send_world_hdri"
    bl_label = "Send HDRI"
    bl_description = "Sends the World's Environment Texture image to 3d-art-api, for Material Preview"

    def execute(self, context):
        project_id = get_project_id(context)
        if not project_id:
            self.report({"ERROR"}, "Set a Project ID in the 3D Art panel before sending")
            return {"CANCELLED"}

        payload = build_world_hdri_sync(context)
        if payload is None:
            self.report({"WARNING"}, "World has no Environment Texture node with an image assigned")
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
