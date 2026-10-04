"""Account buttons: Connect (device pairing approved in the browser),
Cancel, Open browser again, Disconnect, the local dev-server shortcut, and
Open Preferences for Online Access.
"""

import socket

import bpy

from . import api_client, credentials, runtime, status
from .connection import is_local

_NAME_MAX = 60
_TIMEOUT_S = 10.0


def device_name() -> str:
    """How the browser lists this computer: its hostname."""
    return (socket.gethostname() or "").strip()[:_NAME_MAX] or "Blender"


class ART3D_OT_connect(bpy.types.Operator):
    bl_idname = "art3d.connect"
    bl_label = "Connect account"
    bl_description = "Connects this computer to your 3D Art account: approve the code in the browser that opens"

    @classmethod
    def poll(cls, context):
        current = status.current()
        if current.connected or current.state == status.WAITING_APPROVAL:
            cls.poll_message_set(current.message)
            return False
        if not current.online:
            cls.poll_message_set(status.ONLINE_OFF_TEXT)
            return False
        return True

    def execute(self, context):
        runtime.connection().start_pairing(device_name())
        runtime.refresh()
        return {"FINISHED"}


class ART3D_OT_cancel_connect(bpy.types.Operator):
    bl_idname = "art3d.cancel_connect"
    bl_label = "Cancel"
    bl_description = "Stops waiting for the approval in the browser"

    @classmethod
    def poll(cls, context):
        return status.current().state == status.WAITING_APPROVAL

    def execute(self, context):
        runtime.connection().cancel_pairing()
        runtime.refresh()
        return {"FINISHED"}


class ART3D_OT_reopen_link(bpy.types.Operator):
    bl_idname = "art3d.reopen_link"
    bl_label = "Open browser again"
    bl_description = "Opens the approval page for this code again"

    @classmethod
    def poll(cls, context):
        current = status.current()
        return current.state == status.WAITING_APPROVAL and bool(current.verification_url)

    def execute(self, context):
        runtime.open_url(status.current().verification_url)
        return {"FINISHED"}


class ART3D_OT_disconnect(bpy.types.Operator):
    bl_idname = "art3d.disconnect"
    bl_label = "Disconnect"
    bl_description = "Disconnects this computer from your 3D Art account and revokes its device token"

    @classmethod
    def poll(cls, context):
        return status.current().connected

    def execute(self, context):
        runtime.connection().disconnect()
        runtime.refresh()
        self.report({"INFO"}, "Disconnected from 3D Art")
        return {"FINISHED"}


class ART3D_OT_dev_connect(bpy.types.Operator):
    bl_idname = "art3d.dev_connect"
    bl_label = "Dev: connect without browser"
    bl_description = "Local development server only: connects to its dev account without the approval page"

    @classmethod
    def poll(cls, context):
        current = status.current()
        return not current.connected and current.dev_available and is_local(current.server_url)

    def execute(self, context):
        connection = runtime.connection()
        entry, error = _dev_token(connection.server_url(), device_name())
        if entry is None:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        connection.adopt(entry)
        runtime.refresh()
        self.report({"INFO"}, "Connected to the dev account")
        return {"FINISHED"}


class ART3D_OT_open_preferences(bpy.types.Operator):
    bl_idname = "art3d.open_preferences"
    bl_label = "Open Preferences"
    bl_description = "Opens Preferences at System, where Online Access is turned on"

    def execute(self, context):
        bpy.ops.screen.userpref_show(section="SYSTEM")
        return {"FINISHED"}


def _dev_token(server_url: str, name: str) -> tuple:
    """(credentials entry, "") or (None, why not)."""
    try:
        code, data = api_client.request(
            "POST", f"{server_url}/api/dev/device-token", body={"user": "dev", "name": name}, timeout=_TIMEOUT_S
        )
    except api_client.TransportError as error:
        return None, f"Can't reach the server: {error}"
    if not api_client.ok(code) or not isinstance(data, dict) or not isinstance(data.get("deviceToken"), str):
        return None, api_client.error_message(code, data)
    return credentials.from_grant(data["deviceToken"], data.get("device")), ""
