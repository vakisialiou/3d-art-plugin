bl_info = {
    "name": "3D Art Sync",
    "author": "3d-art",
    "version": (0, 1, 0),
    "blender": (5, 2, 1),
    "location": "View3D > Sidebar > 3D Art",
    "description": "Sends the current scene to the 3d-art-api relay for live preview in the browser",
    "category": "Import-Export",
}

import bpy

from . import (
    camera_operators,
    light_operators,
    operators,
    panel,
    project,
    render_settings_operators,
    world_hdri_operators,
    world_operators,
)

_classes = (
    operators.ART3D_OT_send_scene,
    world_operators.ART3D_OT_send_world,
    world_hdri_operators.ART3D_OT_send_world_hdri,
    light_operators.ART3D_OT_send_lighting,
    render_settings_operators.ART3D_OT_send_render_settings,
    camera_operators.ART3D_OT_send_camera,
    panel.ART3D_PT_main_panel,
)


def register():
    project.register_properties()
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    project.unregister_properties()


if __name__ == "__main__":
    register()
