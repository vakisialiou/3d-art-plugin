"""The Send buttons: Send All, Cancel, Resend Everything, and the shared
base every per-channel button (operators.py, light_operators.py, …) builds
on. A button starts a Send job (send_job.py) and returns at once; the job
runs from a timer. In background mode it runs to the end inside execute().

Shift+click sends everything again, ignoring what the browser says it has.
"""

import bpy

from . import send_job

_SCOPES = [
    ("panel", "Panel", "The panel's Selected / All choice"),
    ("selected", "Selected", "The selected objects (plus their parents, for the hierarchy)"),
    ("all", "All", "The whole scene"),
]


def register_properties() -> None:
    bpy.types.Scene.art3d_scope = bpy.props.EnumProperty(
        name="Send",
        description="What the Send buttons cover",
        items=[
            ("SELECTED", "Selected", "The selected objects, lights and cameras (plus parents of selected objects)"),
            ("ALL", "All", "Everything in the scene"),
        ],
        default="ALL",
    )


def unregister_properties() -> None:
    del bpy.types.Scene.art3d_scope


class SendChannelBase:
    """Mixin for one channel's Send button; subclasses set `channels`."""

    channels: tuple = ()

    scope: bpy.props.EnumProperty(items=_SCOPES, default="panel", options={"SKIP_SAVE"})
    force: bpy.props.BoolProperty(
        name="Resend",
        description="Send everything again, even what the browser already has",
        default=False,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return send_job.can_send(cls, context)

    def invoke(self, context, event):
        self.force = self.force or event.shift
        return self.execute(context)

    def execute(self, context):
        scope = context.scene.art3d_scope if self.scope == "panel" else self.scope.upper()
        job = send_job.start(context, self.channels, scope, self.force)
        if job.report is not None and not job.report.ok:
            self.report({"ERROR"}, job.report.message)
            return {"CANCELLED"}
        if job.report is not None:
            self.report({"INFO"}, job.report.message)
        return {"FINISHED"}


class ART3D_OT_send_all(SendChannelBase, bpy.types.Operator):
    bl_idname = "art3d.send_all"
    bl_label = "Send All"
    bl_description = (
        "Sends objects, lights, camera, sky, HDRI and render settings to the browser. "
        "Unchanged objects are skipped; Shift+click sends everything again"
    )

    channels = send_job.CHANNELS


class ART3D_OT_resend_all(SendChannelBase, bpy.types.Operator):
    bl_idname = "art3d.resend_all"
    bl_label = "Resend Everything"
    bl_description = "Bakes, exports and sends the whole scene again, ignoring what the browser already has"

    channels = send_job.CHANNELS

    def invoke(self, context, event):
        self.force = True
        self.scope = "all"
        return self.execute(context)


class ART3D_OT_cancel_send(bpy.types.Operator):
    bl_idname = "art3d.cancel_send"
    bl_label = "Cancel"
    bl_description = "Stops the Send after the current step; what was already sent stays in the browser"

    @classmethod
    def poll(cls, context):
        return send_job.active() is not None

    def execute(self, context):
        send_job.cancel_active()
        return {"FINISHED"}
