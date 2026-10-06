import bpy

from .send_operators import SendChannelBase


class ART3D_OT_send_lighting(SendChannelBase, bpy.types.Operator):
    bl_idname = "art3d.send_lighting"
    bl_label = "Send Lights"
    bl_description = "Sends Light objects (type, color, energy, position, direction, shape, shadow filter, normalize)"

    channels = ("lights",)
