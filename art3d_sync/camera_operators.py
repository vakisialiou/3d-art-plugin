import bpy

from .send_operators import SendChannelBase


class ART3D_OT_send_camera(SendChannelBase, bpy.types.Operator):
    bl_idname = "art3d.send_camera"
    bl_label = "Send Camera"
    bl_description = "Sends Camera objects' optics (lens, sensor, shift, clip, ortho)"

    channels = ("camera",)
