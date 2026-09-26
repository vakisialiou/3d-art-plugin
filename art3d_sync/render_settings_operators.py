import time

import bpy

from .constants import DEV_TOKEN, SERVER_URL
from .project import get_project_id
from .render_settings_sync import build_render_settings_sync
from .socket_client import SocketIOEmitError, emit_once


class ART3D_OT_send_render_settings(bpy.types.Operator):
    bl_idname = "art3d.send_render_settings"
    bl_label = "Send Render Settings"
    bl_description = "Sends exposure, view transform, and render resolution to 3d-art-api"

    def execute(self, context):
        project_id = get_project_id(context)
        if not project_id:
            self.report({"ERROR"}, "Set a Project ID in the 3D Art panel before sending")
            return {"CANCELLED"}

        payload = {
            "timestamp": int(time.time() * 1000),
            **build_render_settings_sync(context),
        }

        try:
            emit_once(
                SERVER_URL,
                "blender-render-settings-sync",
                payload,
                auth={"token": DEV_TOKEN, "projectId": project_id},
            )
        except SocketIOEmitError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        self.report({"INFO"}, "Sent Render Settings to 3D Art")
        return {"FINISHED"}
