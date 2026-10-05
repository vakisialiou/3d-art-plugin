"""Scene project buttons: refresh the account's project list, create a
project for this .blend and bind the scene to it, open the bound project in
the browser.
"""

import os
from urllib.parse import quote

import bpy

from . import api_client, project, runtime, status

_NAME_MAX = 80  # the server's limit
_TIMEOUT_S = 10.0
# States where the server answered for this device, so its project calls work.
_SERVER_STATES = (status.NO_PROJECT, status.NO_BROWSER, status.READY)


class ART3D_OT_refresh_projects(bpy.types.Operator):
    bl_idname = "art3d.refresh_projects"
    bl_label = "Refresh Projects"
    bl_description = "Fetches this account's project list again"

    @classmethod
    def poll(cls, context):
        current = status.current()
        if current.state not in _SERVER_STATES:
            cls.poll_message_set(current.message)
            return False
        return True

    def execute(self, context):
        runtime.connection().want_projects(force=True)
        return {"FINISHED"}


class ART3D_OT_new_project(bpy.types.Operator):
    bl_idname = "art3d.new_project"
    bl_label = "New project"
    bl_description = "Creates a 3D Art project named after this .blend file (or the scene) and binds this scene to it"

    name: bpy.props.StringProperty(
        name="Name",
        description="The new project's name; empty uses the .blend file's or the scene's name",
        default="",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        current = status.current()
        if current.state not in _SERVER_STATES:
            cls.poll_message_set(current.message)
            return False
        return True

    def execute(self, context):
        name = (self.name.strip() or default_name(context))[:_NAME_MAX]
        created, error = _create(name)
        if created is None:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        project.bind(context.scene, created["id"], created["name"])
        runtime.refresh()
        self.report({"INFO"}, f"Created project {created['name']}")
        return {"FINISHED"}


class ART3D_OT_open_project(bpy.types.Operator):
    bl_idname = "art3d.open_project"
    bl_label = "Open in browser"
    bl_description = "Opens this scene's project in the 3D Art web app"

    @classmethod
    def poll(cls, context):
        current = status.current()
        return bool(current.project_id and current.web_url)

    def execute(self, context):
        current = status.current()
        runtime.open_url(f"{current.web_url}/?project={quote(current.project_id)}")
        return {"FINISHED"}


def default_name(context) -> str:
    stem = os.path.splitext(bpy.path.basename(bpy.data.filepath))[0]
    return stem or context.scene.name or "Untitled"


def _create(name: str) -> tuple:
    """POST /api/projects → ({id, name}, "") or (None, why not)."""
    connection = runtime.connection()
    session = connection.session()
    if session is None:
        return None, status.NOT_CONNECTED_TEXT
    try:
        code, data = api_client.request(
            "POST", f"{session.server_url}/api/projects", token=session.token, body={"name": name}, timeout=_TIMEOUT_S
        )
    except api_client.TransportError as error:
        return None, f"Can't reach the server: {error}"
    if code == 401:
        connection.revoked(session.generation)
        return None, status.REVOKED_TEXT
    if not api_client.ok(code) or not isinstance(data, dict) or not isinstance(data.get("id"), str):
        return None, api_client.error_message(code, data)
    created = {"id": data["id"], "name": str(data.get("name") or name)}
    connection.add_project(session.generation, created["id"], created["name"])
    return created, ""
