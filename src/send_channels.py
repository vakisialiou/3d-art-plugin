"""The small channels a Send carries — render settings, sky, cameras,
lights — built on the main thread from the scene: a payload, or the reason
this scene has nothing to send there (shown in the channel's row). Lights
and cameras cover what the Objects row covers (scene_graph.data_objects).
"""

import time
from dataclasses import dataclass
from typing import Optional

import bpy

from .camera_sync import build_camera_sync
from .light_sync import build_light_sync
from .render_settings_sync import build_render_settings_sync
from .scene_graph import data_objects
from .world_sync import SUPPORTED_SKY_TYPES, build_world_sync, emitter_strength, find_world_sky


class SendContext:
    """What the *_sync collectors read from a context: the job's own scene
    and view layer, whatever window happens to be active."""

    def __init__(self, scene: bpy.types.Scene, view_layer: bpy.types.ViewLayer):
        self.scene = scene
        self.view_layer = view_layer


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


def _skip_reason(context: SendContext, scope: str, object_type: str, noun: str) -> str:
    """Why a Lights/Camera row has nothing to send: none in the scope, or only ones Skip Hidden leaves out."""
    if data_objects(context.scene, context.view_layer, scope, False, object_type):
        return f"Only {noun}s disabled in renders"
    return f"No {noun} selected" if scope == "SELECTED" else f"No {noun}s in the scene"


def lights(context: SendContext, scope: str, skip_hidden: bool) -> Built:
    found = data_objects(context.scene, context.view_layer, scope, skip_hidden, "LIGHT")
    if not found:
        return Built("blender-lighting-sync", skip=_skip_reason(context, scope, "LIGHT", "light"))
    return Built("blender-lighting-sync", {"timestamp": _timestamp(), "lights": build_light_sync(found)})


def camera(context: SendContext, scope: str, skip_hidden: bool) -> Built:
    found = data_objects(context.scene, context.view_layer, scope, skip_hidden, "CAMERA")
    if not found:
        return Built("blender-camera-sync", skip=_skip_reason(context, scope, "CAMERA", "camera"))
    return Built("blender-camera-sync", {"timestamp": _timestamp(), "cameras": build_camera_sync(found)})


def build(channel: str, context: SendContext, scope: str, skip_hidden: bool) -> Built:
    if channel == "render":
        return render(context)
    if channel == "sky":
        return sky(context)
    if channel == "lights":
        return lights(context, scope, skip_hidden)
    return camera(context, scope, skip_hidden)
