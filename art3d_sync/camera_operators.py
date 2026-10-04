import time

import bpy

from . import upload
from .camera_sync import build_camera_sync, collect_all_scene_cameras, collect_selected_cameras


class ART3D_OT_send_camera(bpy.types.Operator):
    bl_idname = "art3d.send_camera"
    bl_label = "Send Camera"
    bl_description = "Sends Camera objects' optics (lens, sensor, shift, clip, ortho) to 3d-art-api"

    scope: bpy.props.EnumProperty(
        items=[
            ("selected", "Selected", "Send the selected Camera objects"),
            ("all", "All", "Send every Camera object in the scene"),
        ],
        default="selected",
    )

    @classmethod
    def poll(cls, context):
        return upload.can_send(cls, context)

    def execute(self, context):
        cameras = collect_selected_cameras(context) if self.scope == "selected" else collect_all_scene_cameras(context)
        if not cameras:
            message = "Nothing to send — select a camera first" if self.scope == "selected" else "Scene has no cameras"
            self.report({"WARNING"}, message)
            return {"CANCELLED"}

        def build(_progress):
            return {
                "timestamp": int(time.time() * 1000),
                "cameras": build_camera_sync(cameras),
            }

        if upload.send(self, context, "blender-camera-sync", build) is None:
            return {"CANCELLED"}
        self.report({"INFO"}, f"Sent {len(cameras)} camera(s) to 3D Art")
        return {"FINISHED"}
