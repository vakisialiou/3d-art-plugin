import bpy

from .send_operators import SendChannelBase


class ART3D_OT_send_world_hdri(SendChannelBase, bpy.types.Operator):
    bl_idname = "art3d.send_world_hdri"
    bl_label = "Send HDRI"
    bl_description = (
        "Sends the World's Environment Texture image if one is assigned, otherwise "
        "bakes the procedural Sky Texture into an equirectangular HDRI — for Material Preview"
    )

    channels = ("hdri",)
