"""The send half of the 3D Art panel: Selected/All, one row per channel
(what the scene has, how its Send is going, its own button), the progress
of a running Send, the after-send report and the Web Optimization section.
"""

import time

from . import bake_device, scene_graph, send_job
from .send_job import CHANNELS, DRAW_CALL_WARNING
from .ui_text import ago, alert, duration, megabytes, note, primary, thousands, wrap
from .world_hdri_sync import describe_world_hdri_source, hdri_problem
from .world_sync import find_world_sky

_ROWS = {
    "objects": ("Objects", "OBJECT_DATA", "art3d.send_scene"),
    "lights": ("Lights", "LIGHT", "art3d.send_lighting"),
    "camera": ("Camera", "CAMERA_DATA", "art3d.send_camera"),
    "sky": ("Sky", "WORLD", "art3d.send_world"),
    "hdri": ("HDRI", "IMAGE_DATA", "art3d.send_world_hdri"),
    "render": ("Render", "SCENE", "art3d.send_render_settings"),
}
_SKY_NAMES = {
    "SINGLE_SCATTERING": "Single scattering",
    "MULTIPLE_SCATTERING": "Multiple scattering",
    "PREETHAM": "Preetham",
    "HOSEK_WILKIE": "Hosek-Wilkie",
}

# Row summaries are recounted at most this often while the panel redraws.
_SUMMARY_TTL_S = 1.0
_summary_cache: dict = {}


def _summary(context) -> dict:
    scene = context.scene
    settings = scene.art3d_web
    cache_key = (scene.name_full, scene.art3d_scope, settings.skip_hidden)
    cached = _summary_cache.get(cache_key)
    now = time.monotonic()
    if cached is not None and now - cached[0] < _SUMMARY_TTL_S:
        return cached[1]
    found = scene_graph.summary(scene, context.view_layer, scene.art3d_scope, settings.skip_hidden)
    found["sky"] = _sky_text(scene)
    found["hdri"] = describe_world_hdri_source(context) or "None"
    found["hdri_problem"] = hdri_problem(scene)
    view = scene.view_settings.view_transform
    found["render"] = f"{view} · {scene.render.resolution_x}×{scene.render.resolution_y}"
    _summary_cache.clear()
    _summary_cache[cache_key] = (now, found)
    return found


def _sky_text(scene) -> str:
    found = find_world_sky(scene.world)
    if found is None:
        return "No sky"
    return _SKY_NAMES.get(found[0].sky_type, found[0].sky_type.title())


def _info(channel: str, found: dict) -> str:
    if channel == "objects":
        return f"{found['objects']} · {found['materials']} materials"
    if channel == "lights":
        return str(found["lights"])
    if channel == "camera":
        return str(found["cameras"])
    if channel == "hdri":
        return "From the sky" if found["hdri"].startswith("Sky Texture") else found["hdri"]
    return found[channel]


def draw_scope(layout, context, enabled: bool) -> None:
    row = layout.row()
    row.enabled = enabled
    row.prop(context.scene, "art3d_scope", expand=True)


def draw_rows(layout, context, enabled: bool) -> None:
    """One row per channel: icon and name, its summary or Send state, its button."""
    job = send_job.active()
    report = send_job.report_for(context.scene) if job is None else None
    found = _summary(context)
    box = layout.box()
    column = box.column(align=True)
    column.active = enabled or job is not None
    now = time.time()
    for channel in CHANNELS:
        name, icon, operator = _ROWS[channel]
        split = column.split(factor=0.34, align=True)
        split.label(text=name, icon=icon)
        right = split.row(align=True)
        if job is not None:
            _draw_job_cell(right, job, channel)
            continue
        info = right.row()
        if report is not None and channel in report.rows and report.rows[channel].state != "idle":
            _draw_report_cell(info, report, channel, now)
        elif channel == "hdri" and found["hdri_problem"]:
            info.alert = True
            info.label(text=found["hdri_problem"])
        else:
            info.active = False
            info.label(text=_info(channel, found))
        button = right.row(align=True)
        button.enabled = enabled
        button.operator(operator, text="", icon="EXPORT")


def _draw_job_cell(layout, job, channel: str) -> None:
    row = job.rows[channel]
    if row.state == "working" and channel == "objects":
        sent, total = job.objects_progress()
        layout.progress(factor=sent / total if total else 0.0, type="BAR", text=f"{sent} of {total}")
        return
    cell = layout.row()
    if row.state == "working":
        cell.label(text="Sending…", icon="TIME")
    elif row.state == "sent":
        cell.active = False
        cell.label(text="Sent", icon="CHECKMARK")
    elif row.state == "skipped":
        cell.active = False
        cell.label(text=row.note or "Skipped")
    elif row.state == "failed":
        cell.alert = True
        cell.label(text=row.note or "Failed")
    elif row.state == "waiting":
        cell.active = False
        cell.label(text="Waiting")
    else:
        cell.active = False
        cell.label(text="—")


def _draw_report_cell(layout, report, channel: str, now: float) -> None:
    row = report.rows[channel]
    if row.state == "sent":
        layout.active = False
        layout.label(text=f"Sent {ago(report.finished_at, now)}", icon="CHECKMARK")
    elif row.state == "skipped":
        layout.active = False
        layout.label(text=row.note or "Nothing to send")
    else:
        layout.alert = True
        layout.label(text=row.note or "Not sent")


def draw_progress(layout, job) -> None:
    fraction = job.fraction()
    row = layout.row()
    row.scale_y = 1.3
    row.progress(factor=fraction, type="BAR", text=f"{round(fraction * 100)}% · {job.stage}")
    if job.paused:
        alert(layout, job.paused, icon="PAUSE")
    layout.operator("art3d.cancel_send", text="Cancel", icon="X")


def draw_send_all(layout, enabled: bool) -> None:
    primary(layout, "art3d.send_all", "Send All", "EXPORT", enabled=enabled)


def draw_report(layout, context) -> None:
    report = send_job.report_for(context.scene)
    if report is None:
        return
    now = time.time()
    if not report.ok:
        box = layout.box()
        alert(box, report.message)
        wrap(box, context, f"Stopped after {duration(report.seconds)}. What was sent stays in the browser.", icon="BLANK1")
        return
    failed = any(row.state == "failed" for row in report.rows.values())
    layout.label(text=report.message, icon="ERROR" if failed else "CHECKMARK")
    note(layout, f"In {duration(report.seconds)} · {ago(report.finished_at, now)}", icon="BLANK1")
    if not report.objects:
        return
    box = layout.box()
    column = box.column(align=True)
    column.label(text="In the browser", icon="INFO")
    tris = f"{thousands(report.triangles)} triangles"
    if report.draw_calls > DRAW_CALL_WARNING:
        warning = column.row()
        warning.alert = True
        warning.label(text=f"{report.draw_calls:,} draw calls: above {DRAW_CALL_WARNING:,}", icon="ERROR")
        note(column, tris, icon="BLANK1")
        note(column, "Join objects or use fewer materials", icon="BLANK1")
    else:
        note(column, f"{tris} · {report.draw_calls:,} draw calls", icon="BLANK1")
    if report.unchanged:
        note(column, f"{report.exported} exported · {report.unchanged} unchanged", icon="BLANK1")
    sent = f"{megabytes(report.bytes_sent)} sent"
    if report.texture_bytes:
        sent += f" · textures {megabytes(report.texture_bytes)} in GPU"
    note(column, sent, icon="BLANK1")


def draw_web_settings(layout, context) -> None:
    header, body = layout.panel("art3d_web_optimization", default_closed=True)
    header.label(text="Web Optimization")
    if body is None:
        return
    settings = context.scene.art3d_web
    column = body.column()
    column.use_property_split = True
    column.use_property_decorate = False
    column.enabled = send_job.active() is None
    column.prop(settings, "max_texture")
    column.prop(settings, "bake_size")
    if settings.bake_size == "AUTO":
        column.prop(settings, "texel_density")
    column.prop(settings, "hdri_size")
    column.prop(settings, "texture_format")
    column.prop(settings, "mesh_compression")
    column.prop(settings, "skip_hidden")
    gpu = "" if bake_device.gpu_broken() else bake_device.gpu_hint()
    if bake_device.gpu_broken():
        hint = body.box()
        hint.label(text="The GPU failed", icon="ERROR")
        wrap(hint, context, "Bakes run on the CPU until Blender restarts.", icon="BLANK1")
    if gpu:
        hint = body.box()
        hint.label(text="Bakes run on the CPU", icon="INFO")
        wrap(hint, context, f"Enable {gpu} in Preferences › System for faster Sends.", icon="BLANK1")
        hint.operator("art3d.open_preferences", text="Open Preferences", icon="PREFERENCES")
    body.operator("art3d.resend_all", icon="FILE_REFRESH")
