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

from . import light_operators, operators, panel, render_settings_operators, world_operators

_classes = (
    operators.ART3D_OT_send_scene,
    world_operators.ART3D_OT_send_world,
    light_operators.ART3D_OT_send_lighting,
    render_settings_operators.ART3D_OT_send_render_settings,
    panel.ART3D_PT_main_panel,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
