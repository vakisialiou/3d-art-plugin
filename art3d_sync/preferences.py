"""Add-on preferences: the server URL override, shown only with Developer
Extras on. Resolution order: env ART3D_SERVER_URL > this field > the default.
"""

import os

import bpy

from .constants import DEFAULT_SERVER_URL

_ENV_SERVER_URL = "ART3D_SERVER_URL"


class ART3D_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    server_url: bpy.props.StringProperty(
        name="Server URL",
        description="The 3D Art server this add-on connects to; empty uses the default",
        default="",
    )

    def draw(self, context):
        layout = self.layout
        if context.preferences.view.show_developer_ui:
            layout.prop(self, "server_url")
            layout.label(text=f"In use: {server_url()}")
        else:
            layout.label(text="Connect your account in the 3D Viewport's sidebar, 3D Art tab")


def server_url() -> str:
    url = os.environ.get(_ENV_SERVER_URL, "").strip()
    if not url:
        addon = bpy.context.preferences.addons.get(__package__)
        preferences = addon.preferences if addon is not None else None
        url = preferences.server_url.strip() if preferences is not None else ""
    return (url or DEFAULT_SERVER_URL).rstrip("/")
