"""Which 3D Art project a scene sends to: the project id (set by the Scene
project dropdown or New project, never typed — the raw field shows only with
Developer Extras on) and its cached display name. Plain scene data, not
secrets: .blend files get shared, and a shared file keeps its binding until
someone picks another project.
"""

import bpy


def register_properties() -> None:
    bpy.types.Scene.art3d_project_id = bpy.props.StringProperty(
        name="Project ID",
        description="The 3D Art project this scene sends to",
        default="",
    )
    bpy.types.Scene.art3d_project_name = bpy.props.StringProperty(
        name="Project Name",
        description="The bound project's name as the server last reported it",
        default="",
    )


def unregister_properties() -> None:
    del bpy.types.Scene.art3d_project_name
    del bpy.types.Scene.art3d_project_id


def scene_project_id(scene: bpy.types.Scene) -> str:
    return scene.art3d_project_id.strip()


def get_project_id(context: bpy.types.Context) -> str:
    return scene_project_id(context.scene)


def bind(scene: bpy.types.Scene, project_id: str, name: str) -> None:
    scene.art3d_project_id = project_id
    scene.art3d_project_name = name
