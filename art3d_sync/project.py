"""Which web project this .blend syncs to. A registered Scene property (not a
raw custom property) so the N-panel can show it as an editable field.
"""

import bpy

_PROP_NAME = "art3d_project_id"


def register_properties() -> None:
    bpy.types.Scene.art3d_project_id = bpy.props.StringProperty(
        name="Project ID",
        description=(
            "Must match the Project ID shown in the 3D Art web app's Sync tab — "
            "scopes this scene's sync to that browser tab"
        ),
        default="",
    )


def unregister_properties() -> None:
    del bpy.types.Scene.art3d_project_id


def get_project_id(context: bpy.types.Context) -> str:
    return context.scene.art3d_project_id.strip()
