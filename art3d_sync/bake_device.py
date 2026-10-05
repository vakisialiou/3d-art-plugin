"""Cycles bakes on the GPU when Preferences › System › Cycles Render Devices
has one enabled — several times faster than the CPU default. The add-on
never changes that preference itself; the panel only points at it when a
GPU sits there unused (gpu_hint). A GPU that fails (a kernel that won't
load, out of memory) is given up for the session: the step reruns on the
CPU, and so does every bake after it.
"""

from contextlib import contextmanager
from typing import Optional

import bpy

_GPU_TYPES = ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL")

# get_devices_for_type() enumerates hardware (slow-ish): asked once a session.
_unused_gpu: Optional[str] = None
_checked = False
_broken = False

_DEVICE_WORDS = ("OptiX", "OPTIX", "CUDA", "HIP", "oneAPI", "ONEAPI", "Metal", "METAL", "kernel", "device")


def _cycles_preferences():
    addon = bpy.context.preferences.addons.get("cycles")
    return addon.preferences if addon is not None else None


def gpu_enabled() -> bool:
    if _broken:
        return False
    preferences = _cycles_preferences()
    if preferences is None or preferences.compute_device_type == "NONE":
        return False
    return any(device.use and device.type != "CPU" for device in preferences.devices)


@contextmanager
def render_device(scene: bpy.types.Scene):
    """Cycles work inside runs on the GPU if one is enabled (and hasn't
    failed), else explicitly on the CPU — whatever device the .blend itself
    asks for; the scene's own setting comes back after."""
    previous = scene.cycles.device
    scene.cycles.device = "GPU" if gpu_enabled() else "CPU"
    try:
        yield
    finally:
        scene.cycles.device = previous


def is_device_error(error: BaseException) -> bool:
    return any(word in str(error) for word in _DEVICE_WORDS)


def give_up_gpu() -> None:
    global _broken
    _broken = True


def gpu_broken() -> bool:
    return _broken


def gpu_hint() -> str:
    """The name of a GPU Cycles could bake on but isn't set to, else ""."""
    global _unused_gpu, _checked
    if gpu_enabled():
        return ""
    if not _checked:
        _checked = True
        preferences = _cycles_preferences()
        if preferences is not None:
            for device_type in _GPU_TYPES:
                try:
                    devices = preferences.get_devices_for_type(device_type)
                except (TypeError, ValueError, RuntimeError):
                    continue
                gpu = next((device for device in devices if device.type != "CPU"), None)
                if gpu is not None:
                    _unused_gpu = gpu.name
                    break
    return _unused_gpu or ""
