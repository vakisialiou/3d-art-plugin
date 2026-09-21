import time

import bpy

from .camera_sync import build_camera_sync, collect_all_scene_cameras, collect_selected_cameras
from .constants import DEV_TOKEN, SERVER_URL
from .project import get_project_id
from .socket_client import SocketIOEmitError, emit_once


class ART3D_OT_send_camera(bpy.types.Operator):
    bl_idname = "art3d.send_camera"
    bl_label = "Send Camera"
    bl_description = "Sends Camera objects' optics (lens, sensor, clip, ortho) to 3d-art-api"

    scope: bpy.props.EnumProperty(
        items=[
            ("selected", "Selected", "Send the selected Camera objects"),
            ("all", "All", "Send every Camera object in the scene"),
        ],
        default="selected",
    )

    def execute(self, context):
        project_id = get_project_id(context)
        if not project_id:
            self.report({"ERROR"}, "Set a Project ID in the 3D Art panel before sending")
            return {"CANCELLED"}

        cameras = collect_selected_cameras(context) if self.scope == "selected" else collect_all_scene_cameras(context)
        if not cameras:
            message = "Nothing to send — select a camera first" if self.scope == "selected" else "Scene has no cameras"
            self.report({"WARNING"}, message)
            return {"CANCELLED"}

        payload = {
            "timestamp": int(time.time() * 1000),
            "cameras": build_camera_sync(cameras),
        }

        try:
            emit_once(
                SERVER_URL,
                "blender-camera-sync",
                payload,
                auth={"token": DEV_TOKEN, "projectId": project_id},
            )
        except SocketIOEmitError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        self.report({"INFO"}, f"Sent {len(cameras)} camera(s) to 3D Art")
        return {"FINISHED"}
