"""Ids included in the last successful `blender-sync`, persisted on the Scene.
operators.py diffs the current scene against it to emit `action: 'delete'`
entries — the only way the browser learns an object was deleted.
"""

import bpy

_SENT_IDS_PROP = "art3d_sent_ids"


def get_previous_sent_ids(scene: bpy.types.Scene) -> set:
    stored = scene.get(_SENT_IDS_PROP, "")
    return set(stored.split(",")) if stored else set()


def set_sent_ids(scene: bpy.types.Scene, ids: set) -> None:
    scene[_SENT_IDS_PROP] = ",".join(sorted(ids))
