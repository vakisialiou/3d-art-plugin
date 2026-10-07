"""Ids included in the last successful `blender-sync`, persisted on the Scene.
scene_graph.plan() diffs the current scene against it to emit `action:
'delete'` entries — the only way the browser learns an object was deleted.
link_journal.py keeps it until the file is saved, and this session remembers
it too: an undo rolls the property back.
"""

import bpy

from . import link_journal

_SENT_IDS_PROP = "skyray_sent_ids"
# Scene session_uid → the value this session last wrote.
_session: dict = {}


def get_previous_sent_ids(scene: bpy.types.Scene) -> set:
    stored = _session.get(scene.session_uid)
    if stored is None:
        stored = scene.get(_SENT_IDS_PROP, "")
    return set(stored.split(",")) if stored else set()


def set_sent_ids(scene: bpy.types.Scene, ids: set) -> None:
    value = ",".join(sorted(ids))
    scene[_SENT_IDS_PROP] = value
    _session[scene.session_uid] = value
    link_journal.record([(scene, _SENT_IDS_PROP, value)])
