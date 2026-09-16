import time

import bpy

from .constants import SERVER_URL
from .socket_client import SocketIOEmitError, emit_once
from .world_sync import build_world_sync


class ART3D_OT_send_world(bpy.types.Operator):
    bl_idname = "art3d.send_world"
    bl_label = "Send Sky"
    bl_description = "Sends the World's Sky Texture (sun position, atmosphere) to 3d-art-api"

    def execute(self, context):
        sky = build_world_sync(context)
        if sky is None:
            self.report({"WARNING"}, "World has no Sky Texture node to send")
            return {"CANCELLED"}

        payload = {"timestamp": int(time.time() * 1000), "sky": sky}

        try:
            emit_once(SERVER_URL, "blender-world-sync", payload)
        except SocketIOEmitError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        self.report({"INFO"}, "Sent Sky settings to 3D Art")
        return {"FINISHED"}
