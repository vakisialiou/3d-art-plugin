import bpy

from .send_operators import SendChannelBase


class ART3D_OT_send_scene(SendChannelBase, bpy.types.Operator):
    bl_idname = "art3d.send_scene"
    bl_label = "Send Objects"
    bl_description = (
        "Bakes and exports objects (geometry + materials) and sends those the browser doesn't have yet; "
        "Shift+click sends them all again"
    )

    channels = ("objects",)
