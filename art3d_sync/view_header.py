"""The 3D Art button in the 3D Viewport's header: the status dot (a popover
with the setup card or project) and Send All — or a running Send's progress
and Cancel. Hidden with the add-on preference."""

import bpy

from . import connection_ui, preferences, send_job, status
from .icons import dot


def _draw(self, context):
    if not preferences.show_header_button():
        return
    job = send_job.active()
    current = status.current()
    color, _ = connection_ui.state_dot(current, context.scene)
    row = self.layout.row(align=True)
    if job is not None:
        bar = row.row(align=True)
        bar.ui_units_x = 5
        fraction = job.fraction()
        bar.progress(factor=fraction, type="BAR", text=f"{round(fraction * 100)}%")
    row.popover(panel="ART3D_PT_status", text="3D Art", icon_value=dot(color))
    if job is not None:
        row.operator("art3d.cancel_send", text="", icon="X")
    else:
        row.operator("art3d.send_all", text="", icon="EXPORT")


def register() -> None:
    bpy.types.VIEW3D_HT_header.append(_draw)


def unregister() -> None:
    bpy.types.VIEW3D_HT_header.remove(_draw)
