"""The Account and Scene project boxes, drawn by both the 3D Art N-panel and
the status-bar popover. Drawing never waits on the network: it reads
status.current(), and asking for the project list or the dev check only
flags work for the connection worker.
"""

import bpy

from . import runtime, status
from .constants import DEFAULT_SERVER_URL


def draw_account(layout: bpy.types.UILayout, context: bpy.types.Context) -> None:
    current = status.current()
    box = layout.box()
    box.label(text="Account", icon="USER")
    if current.state == status.WAITING_APPROVAL:
        _draw_waiting(box, current)
    elif current.connected:
        _draw_connected(box, current)
    else:
        _draw_not_connected(box, current)
    if current.server_url and current.server_url != DEFAULT_SERVER_URL:
        box.label(text=f"Server: {current.server_url}")


def draw_project(layout: bpy.types.UILayout, context: bpy.types.Context) -> None:
    current = status.current()
    if not current.connected:
        return
    runtime.connection().want_projects()
    scene = context.scene
    box = layout.box()
    box.label(text="Scene project", icon="SCENE_DATA")
    row = box.row(align=True)
    row.prop(scene, "art3d_project_pick", text="")
    row.operator("art3d.refresh_projects", text="", icon="FILE_REFRESH")
    box.operator("art3d.new_project", icon="ADD")
    if current.state not in status.ACCOUNT_STATES:
        box.label(text=current.message, icon=status.ICONS[current.state])
    if current.project_id:
        box.operator("art3d.open_project", icon="URL")
    if context.preferences.view.show_developer_ui:
        box.prop(scene, "art3d_project_id")


def _draw_waiting(box: bpy.types.UILayout, current: status.Status) -> None:
    column = box.column(align=True)
    column.label(text=current.message, icon=status.ICONS[current.state])
    if current.user_code:
        code = column.box().row()
        code.alignment = "CENTER"
        code.scale_y = 1.6
        code.label(text=current.user_code)
        column.label(text="Check that the browser shows this code")
    else:
        column.label(text="Requesting a code…")
    row = box.row(align=True)
    row.operator("art3d.reopen_link", icon="URL")
    row.operator("art3d.cancel_connect", icon="CANCEL")


def _draw_not_connected(box: bpy.types.UILayout, current: status.Status) -> None:
    box.label(text=current.message, icon=status.ICONS[status.NOT_CONNECTED])
    if not current.online:
        box.label(text=status.ONLINE_OFF_TEXT, icon=status.ICONS[status.ONLINE_ACCESS_OFF])
        box.operator("art3d.open_preferences", icon="PREFERENCES")
        return
    box.operator("art3d.connect", icon="LINKED")
    if current.dev_available:
        box.operator("art3d.dev_connect", icon="CONSOLE")
    else:
        runtime.connection().want_dev_check()


def _draw_connected(box: bpy.types.UILayout, current: status.Status) -> None:
    if current.state in status.ACCOUNT_STATES:
        box.label(text=current.message, icon=status.ICONS[current.state])
    else:
        box.label(text="Connected", icon="LINKED")
    column = box.column(align=True)
    if current.email:
        column.label(text=current.email)
    if current.device_name:
        column.label(text=f"Device: {current.device_name}")
    if current.state == status.ONLINE_ACCESS_OFF:
        box.operator("art3d.open_preferences", icon="PREFERENCES")
    box.operator("art3d.disconnect", icon="UNLINKED")
