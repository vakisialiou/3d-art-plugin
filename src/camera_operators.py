import bpy

from .send_operators import SendChannelBase


class SKYRAY_OT_send_camera(SendChannelBase, bpy.types.Operator):
    bl_idname = "skyray.send_camera"
    bl_label = "Send Camera"
    bl_description = "Sends Camera objects' optics (lens, sensor, shift, clip, ortho)"

    channels = ("camera",)
