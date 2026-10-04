"""The Scene project dropdown: the account's projects from the last fetch,
as a virtual enum on the Scene. Its get/set read and write the scene's
binding (project.py), so nothing extra lands in the .blend.
"""

import bpy

from . import project, runtime

_PLACEHOLDER = "NONE"

# Blender keeps only pointers to the strings a dynamic items callback
# returns, so Python must hold the last list.
_items: list = []
# Stable enum values: a list refreshed between drawing the menu and the
# click must not shift the value onto another project. 0 is the placeholder.
_values: dict = {}
_ids: dict = {}


def register_properties() -> None:
    bpy.types.Scene.art3d_project_pick = bpy.props.EnumProperty(
        name="Project",
        description="The 3D Art project this scene sends to",
        items=_list_items,
        get=_get,
        set=_set,
        options=set(),
    )


def unregister_properties() -> None:
    del bpy.types.Scene.art3d_project_pick


def _value(project_id: str) -> int:
    value = _values.get(project_id)
    if value is None:
        value = _values[project_id] = len(_values) + 1
        _ids[value] = project_id
    return value


def _list_items(scene, _context):
    global _items
    connection = runtime.connection()
    connection.want_projects()
    projects = connection.projects()
    bound = project.scene_project_id(scene)
    items = []
    if not bound:
        items.append((_PLACEHOLDER, "Choose a project", "This scene isn't bound to a project yet", "NONE", 0))
    elif bound not in {project_id for project_id, _ in projects}:
        name = scene.art3d_project_name or "Unknown project"
        items.append((bound, name, "The project this scene is bound to", "NONE", _value(bound)))
    for project_id, name in projects:
        items.append((project_id, name, "", "NONE", _value(project_id)))
    _items = items
    return items


def _get(scene) -> int:
    bound = project.scene_project_id(scene)
    return _value(bound) if bound else 0


def _set(scene, value: int) -> None:
    project_id = _ids.get(value)
    if project_id is None or project_id == project.scene_project_id(scene):
        return
    names = dict(runtime.connection().projects())
    project.bind(scene, project_id, names.get(project_id, ""))
    runtime.refresh()
