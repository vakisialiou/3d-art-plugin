import bpy


class ART3D_PT_main_panel(bpy.types.Panel):
    bl_idname = "ART3D_PT_main_panel"
    bl_label = "3D Art"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "3D Art"

    def draw(self, context):
        layout = self.layout

        # Which web project this scene syncs to — required by every send
        # operator (see project.py's get_project_id). Its own box, above
        # General Settings, since every section below depends on it.
        box = layout.box()
        box.label(text="Project", icon="WORLD_DATA")
        box.prop(context.scene, "art3d_project_id", text="Project ID")

        # General Settings — world/sky today; render/shadow settings join this
        # section later, paired two-per-row alongside Send Sky once they exist.
        box = layout.box()
        box.label(text="General Settings", icon="WORLD")
        row = box.row(align=True)
        row.operator("art3d.send_world", text="Send Sky", icon="WORLD")
        row.operator("art3d.send_render_settings", text="Send Render Settings", icon="SETTINGS")

        # Objects
        box = layout.box()
        box.label(text="Objects", icon="OBJECT_DATA")
        row = box.row(align=True)
        row.operator("art3d.send_scene", text="Send Selected", icon="EXPORT").scope = "selected"
        row.operator("art3d.send_scene", text="Send All", icon="SCENE_DATA").scope = "all"

        # Lighting
        box = layout.box()
        box.label(text="Lighting", icon="LIGHT")
        row = box.row(align=True)
        row.operator("art3d.send_lighting", text="Send Selected", icon="EXPORT").scope = "selected"
        row.operator("art3d.send_lighting", text="Send All", icon="SCENE_DATA").scope = "all"

        # Camera
        box = layout.box()
        box.label(text="Camera", icon="CAMERA_DATA")
        row = box.row(align=True)
        row.operator("art3d.send_camera", text="Send Selected", icon="EXPORT").scope = "selected"
        row.operator("art3d.send_camera", text="Send All", icon="SCENE_DATA").scope = "all"
