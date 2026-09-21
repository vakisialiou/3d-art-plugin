"""Which web project this .blend syncs to — a real Scene property (not a raw
custom property like object_id.py's) so it shows as an editable text field in
the N-panel and travels with the .blend file across machines.
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
