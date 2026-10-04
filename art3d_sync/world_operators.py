import time

import bpy

from . import upload
from .world_sync import SUPPORTED_SKY_TYPES, build_world_sync, emitter_strength, find_world_sky


class ART3D_OT_send_world(bpy.types.Operator):
    bl_idname = "art3d.send_world"
    bl_label = "Send Sky"
    bl_description = "Sends the World's Sky Texture (sun position, atmosphere) to 3d-art-api"

    @classmethod
    def poll(cls, context):
        return upload.can_send(cls, context)

    def execute(self, context):
        found = find_world_sky(context.scene.world)
        if found is None:
            self.report({"WARNING"}, "World has no Sky Texture connected to its output to send")
            return {"CANCELLED"}
        sky, emitter = found
        if sky.sky_type not in SUPPORTED_SKY_TYPES:
            self.report(
                {"WARNING"},
                f"Sky type {sky.sky_type} is not supported by the web viewer "
                "(Single/Multiple Scattering only)",
            )
            return {"CANCELLED"}
        strength = emitter_strength(emitter)
        if strength is None:
            self.report(
                {"WARNING"},
                f"{emitter.name} Strength is driven by nodes the web viewer can't evaluate "
                "(only a value or a Value node)",
            )
            return {"CANCELLED"}

        def build(_progress):
            return {
                "timestamp": int(time.time() * 1000),
                "sky": build_world_sync(sky, strength, context.scene.render.engine),
            }

        if upload.send(self, context, "blender-world-sync", build) is None:
            return {"CANCELLED"}
        self.report({"INFO"}, "Sent Sky settings to 3D Art")
        return {"FINISHED"}
