import bpy

from .send_operators import SendChannelBase


class SKYRAY_OT_send_lighting(SendChannelBase, bpy.types.Operator):
    bl_idname = "skyray.send_lighting"
    bl_label = "Send Lights"
    bl_description = "Sends Light objects (type, color, energy, position, direction, shape, shadow filter, normalize)"

    channels = ("lights",)
