"""Tracks which object ids were included in the last successful `blender-sync`
send, scoped to the Scene (persisted as a custom property, survives reopens).
Lets `operators.py` diff the current scene against that record and emit
`action: 'delete'` entries for ids that have vanished from the scene since —
without this, a deleted object stays a ghost on the browser side forever.
"""

import bpy

_SENT_IDS_PROP = "art3d_sent_ids"


def get_previous_sent_ids(scene: bpy.types.Scene) -> set:
    stored = scene.get(_SENT_IDS_PROP, "")
    return set(stored.split(",")) if stored else set()


def set_sent_ids(scene: bpy.types.Scene, ids: set) -> None:
    scene[_SENT_IDS_PROP] = ",".join(sorted(ids))
