import time

import bpy

from . import upload
from .render_settings_sync import build_render_settings_sync


class ART3D_OT_send_render_settings(bpy.types.Operator):
    bl_idname = "art3d.send_render_settings"
    bl_label = "Send Render Settings"
    bl_description = (
        "Sends color management (display, view, look, exposure, gamma, white balance, "
        "curves, dither), render resolution and pixel aspect to 3d-art-api"
    )

    @classmethod
    def poll(cls, context):
        return upload.can_send(cls, context)

    def execute(self, context):
        def build(_progress):
            return {
                "timestamp": int(time.time() * 1000),
                **build_render_settings_sync(context),
            }

        if upload.send(self, context, "blender-render-settings-sync", build) is None:
            return {"CANCELLED"}
        self.report({"INFO"}, "Sent Render Settings to 3D Art")
        return {"FINISHED"}
