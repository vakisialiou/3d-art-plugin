import time

import bpy

from .constants import DEV_TOKEN, SERVER_URL
from .light_sync import build_light_sync, collect_all_scene_lights, collect_selected_lights
from .project import get_project_id
from .socket_client import SocketIOEmitError, emit_once


class ART3D_OT_send_lighting(bpy.types.Operator):
    bl_idname = "art3d.send_lighting"
    bl_label = "Send Lighting"
    bl_description = "Sends Light objects (type, color, energy, position, direction, shape, shadow filter) to 3d-art-api"

    scope: bpy.props.EnumProperty(
        items=[
            ("selected", "Selected", "Send the selected Light objects"),
            ("all", "All", "Send every Light object in the scene"),
        ],
        default="selected",
    )

    def execute(self, context):
        project_id = get_project_id(context)
        if not project_id:
            self.report({"ERROR"}, "Set a Project ID in the 3D Art panel before sending")
            return {"CANCELLED"}

        lights = collect_selected_lights(context) if self.scope == "selected" else collect_all_scene_lights(context)
        if not lights:
            message = "Nothing to send — select a light first" if self.scope == "selected" else "Scene has no lights"
            self.report({"WARNING"}, message)
            return {"CANCELLED"}

        payload = {
            "timestamp": int(time.time() * 1000),
            "lights": build_light_sync(lights),
        }

        try:
            emit_once(
                SERVER_URL,
                "blender-lighting-sync",
                payload,
                auth={"token": DEV_TOKEN, "projectId": project_id},
            )
        except SocketIOEmitError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        self.report({"INFO"}, f"Sent {len(lights)} light(s) to 3D Art")
        return {"FINISHED"}
