import bpy

from .send_operators import SendChannelBase


class ART3D_OT_send_world(SendChannelBase, bpy.types.Operator):
    bl_idname = "art3d.send_world"
    bl_label = "Send Sky"
    bl_description = "Sends the World's Sky Texture (sun position, atmosphere)"

    channels = ("sky",)
