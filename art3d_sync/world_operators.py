import time

import bpy

from .constants import DEV_TOKEN, SERVER_URL
from .project import get_project_id
from .socket_client import SocketIOEmitError, emit_once
from .world_sync import SUPPORTED_SKY_TYPES, build_world_sync, find_world_sky


class ART3D_OT_send_world(bpy.types.Operator):
    bl_idname = "art3d.send_world"
    bl_label = "Send Sky"
    bl_description = "Sends the World's Sky Texture (sun position, atmosphere) to 3d-art-api"

    def execute(self, context):
        project_id = get_project_id(context)
        if not project_id:
            self.report({"ERROR"}, "Set a Project ID in the 3D Art panel before sending")
            return {"CANCELLED"}

        found = find_world_sky(context.scene.world)
        if found is None:
            self.report({"WARNING"}, "World has no Sky Texture node to send")
            return {"CANCELLED"}
        sky, background = found
        if sky.sky_type not in SUPPORTED_SKY_TYPES:
            self.report(
                {"WARNING"},
                f"Sky type {sky.sky_type} is not supported by the web viewer "
                "(Single/Multiple Scattering only)",
            )
            return {"CANCELLED"}

        payload = {"timestamp": int(time.time() * 1000), "sky": build_world_sync(sky, background)}

        try:
            emit_once(
                SERVER_URL,
                "blender-world-sync",
                payload,
                auth={"token": DEV_TOKEN, "projectId": project_id},
            )
        except SocketIOEmitError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        self.report({"INFO"}, "Sent Sky settings to 3D Art")
        return {"FINISHED"}
