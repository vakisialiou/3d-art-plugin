"""The status dots — green ready, amber a step is needed, red a problem,
blue sending, grey not connected — as preview icons (icons/dot_*.png)."""

import os

import bpy
import bpy.utils.previews

_DIRECTORY = os.path.join(os.path.dirname(__file__), "icons")
_NAMES = ("green", "amber", "red", "blue", "grey")

_previews = None


def register() -> None:
    global _previews
    _previews = bpy.utils.previews.new()
    for name in _NAMES:
        _previews.load(name, os.path.join(_DIRECTORY, f"dot_{name}.png"), "IMAGE")


def unregister() -> None:
    global _previews
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None


def dot(name: str) -> int:
    """The icon_value of a status dot; 0 (no icon) before register()."""
    if _previews is None or name not in _previews:
        return 0
    return _previews[name].icon_id
