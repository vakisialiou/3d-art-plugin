"""The 3D Art item in Blender's status bar, always visible: the connection
state in a few words. Clicking it opens the Account and Scene project boxes
as a popover.
"""

import bpy

from . import connection_ui, status

_NAME_MAX = 24

_SHORT = {
    status.NOT_CONNECTED: "not connected",
    status.WAITING_APPROVAL: "approve in browser",
    status.ONLINE_ACCESS_OFF: "online access off",
    status.CONNECTING: "connecting…",
    status.OFFLINE: "offline",
    status.OUTDATED: "update the add-on",
    status.NO_PROJECT: "no project",
}


class ART3D_PT_status(bpy.types.Panel):
    bl_idname = "ART3D_PT_status"
    bl_label = "3D Art"
    bl_space_type = "STATUSBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = 14

    def draw(self, context):
        connection_ui.draw_account(self.layout, context)
        connection_ui.draw_project(self.layout, context)


def text(current: status.Status) -> str:
    if current.state == status.READY:
        return f"3D Art · {_short(current.project_name)} · browser ✓"
    if current.state == status.NO_BROWSER:
        return f"3D Art · {_short(current.project_name)} · no browser"
    return f"3D Art · {_SHORT[current.state]}"


def _short(name: str) -> str:
    name = name or "project"
    return name if len(name) <= _NAME_MAX else name[: _NAME_MAX - 1] + "…"


def _draw(self, _context):
    current = status.current()
    self.layout.popover(panel=ART3D_PT_status.bl_idname, text=text(current), icon=status.ICONS[current.state])


def register() -> None:
    bpy.types.STATUSBAR_HT_header.append(_draw)


def unregister() -> None:
    bpy.types.STATUSBAR_HT_header.remove(_draw)
