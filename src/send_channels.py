"""The small channels a Send carries — render settings, sky, cameras,
lights — built on the main thread from the scene: a payload, or the reason
this scene has nothing to send there (shown in the channel's row).
"""

import time
from dataclasses import dataclass
from typing import Optional

import bpy

from .camera_sync import build_camera_sync
from .light_sync import build_light_sync
from .render_settings_sync import build_render_settings_sync
from .scene_graph import selected_objects
from .world_sync import SUPPORTED_SKY_TYPES, build_world_sync, emitter_strength, find_world_sky


class SendContext:
    """What the *_sync collectors read from a context: the job's own scene
    and selection, whatever window happens to be active."""

    def __init__(self, scene: bpy.types.Scene, view_layer: bpy.types.ViewLayer):
        self.scene = scene
        self.view_layer = view_layer

    @property
    def selected_objects(self) -> list:
        return selected_objects(self.view_layer)


@dataclass
class Built:
    event: str
    payload: Optional[dict] = None
    skip: str = ""


def _timestamp() -> int:
    return int(time.time() * 1000)


def render(context: SendContext) -> Built:
    return Built("blender-render-settings-sync", {"timestamp": _timestamp(), **build_render_settings_sync(context)})


def sky(context: SendContext) -> Built:
    found = find_world_sky(context.scene.world)
    if found is None:
        return Built("blender-world-sync", skip="No Sky Texture in the World")
    sky_node, emitter = found
    if sky_node.sky_type not in SUPPORTED_SKY_TYPES:
        return Built("blender-world-sync", skip=f"Sky type {sky_node.sky_type} isn't supported")
    strength = emitter_strength(emitter)
    if strength is None:
        return Built("blender-world-sync", skip="Sky strength is driven by nodes")
    payload = {
        "timestamp": _timestamp(),
        "sky": build_world_sync(sky_node, strength, context.scene.render.engine),
    }
    return Built("blender-world-sync", payload)


def _objects_of(context: SendContext, scope: str, object_type: str) -> list:
    source = context.selected_objects if scope == "SELECTED" else context.scene.objects
    return [obj for obj in source if obj.type == object_type]


def lights(context: SendContext, scope: str) -> Built:
    found = _objects_of(context, scope, "LIGHT")
    if not found:
        reason = "No light selected" if scope == "SELECTED" else "No lights in the scene"
        return Built("blender-lighting-sync", skip=reason)
    return Built("blender-lighting-sync", {"timestamp": _timestamp(), "lights": build_light_sync(found)})


def camera(context: SendContext, scope: str) -> Built:
    found = _objects_of(context, scope, "CAMERA")
    if not found:
        reason = "No camera selected" if scope == "SELECTED" else "No cameras in the scene"
        return Built("blender-camera-sync", skip=reason)
    return Built("blender-camera-sync", {"timestamp": _timestamp(), "cameras": build_camera_sync(found)})


def build(channel: str, context: SendContext, scope: str) -> Built:
    if channel == "render":
        return render(context)
    if channel == "sky":
        return sky(context)
    if channel == "lights":
        return lights(context, scope)
    return camera(context, scope)
