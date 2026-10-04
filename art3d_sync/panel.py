import bpy

from . import connection_ui, status
from .world_hdri_sync import describe_world_hdri_source


class ART3D_PT_main_panel(bpy.types.Panel):
    bl_idname = "ART3D_PT_main_panel"
    bl_label = "3D Art"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "3D Art"

    def draw(self, context):
        layout = self.layout
        connection_ui.draw_account(layout, context)
        connection_ui.draw_project(layout, context)

        # Send buttons grey out through their poll() until READY.
        sends = layout.column()
        sends.active = status.current().state == status.READY

        box = sends.box()
        box.label(text="General Settings", icon="WORLD")
        row = box.row(align=True)
        row.operator("art3d.send_world", text="Send Sky", icon="WORLD")
        row.operator("art3d.send_world_hdri", text="Send HDRI", icon="IMAGE_DATA")
        row.operator("art3d.send_render_settings", text="Send Render Settings", icon="SETTINGS")
        hdri_source = describe_world_hdri_source(context)
        hdri_status = f"HDRI source: {hdri_source}" if hdri_source else "HDRI source: none"
        box.label(text=hdri_status, icon="INFO")

        box = sends.box()
        box.label(text="Objects", icon="OBJECT_DATA")
        row = box.row(align=True)
        row.operator("art3d.send_scene", text="Send Selected", icon="EXPORT").scope = "selected"
        row.operator("art3d.send_scene", text="Send All", icon="SCENE_DATA").scope = "all"

        box = sends.box()
        box.label(text="Lighting", icon="LIGHT")
        row = box.row(align=True)
        row.operator("art3d.send_lighting", text="Send Selected", icon="EXPORT").scope = "selected"
        row.operator("art3d.send_lighting", text="Send All", icon="SCENE_DATA").scope = "all"

        box = sends.box()
        box.label(text="Camera", icon="CAMERA_DATA")
        row = box.row(align=True)
        row.operator("art3d.send_camera", text="Send Selected", icon="EXPORT").scope = "selected"
        row.operator("art3d.send_camera", text="Send All", icon="SCENE_DATA").scope = "all"
