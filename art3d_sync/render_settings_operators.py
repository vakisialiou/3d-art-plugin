import bpy

from .send_operators import SendChannelBase


class ART3D_OT_send_render_settings(SendChannelBase, bpy.types.Operator):
    bl_idname = "art3d.send_render_settings"
    bl_label = "Send Render Settings"
    bl_description = (
        "Sends color management (display, view, look, exposure, gamma, white balance, "
        "curves, dither), render resolution and pixel aspect"
    )

    channels = ("render",)
