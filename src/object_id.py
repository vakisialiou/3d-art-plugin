"""Stable per-object id, independent of the renameable `obj.name`. Stored as
a custom property, so it persists in the .blend across renames and reopens;
link_journal.py keeps it until the file is saved, and this session remembers
it by session_uid, which an undo keeps while it rolls the property back.
"""

import uuid
from typing import Optional

import bpy

from . import link_journal

_ID_PROP = "skyray_id"
# session_uid → the id this session resolved for that object. Blender never
# reuses a session_uid within a process, so a closed file's entries never match.
_session_ids: dict = {}


def resolve_stable_ids(objects: list) -> dict:
    """Returns {obj.name: stable id} for one sync batch, generating ids where
    missing.

    Blender copies custom properties verbatim on duplicate/paste/append, so a
    duplicate can carry its original's skyray_id. All holders of an id are
    resolved together: the one this session already resolved under it keeps
    it, else the name that sorts first (Blender suffixes the duplicate's
    name, .001 etc., never the original's); the rest get fresh ids —
    deterministic regardless of call order. An object whose property an undo
    rolled back gets the id this session gave it again.

    Keyed by `obj.name`, not `id(obj)`: bpy RNA wrappers aren't the same
    Python instance across access paths (`objects` vs bpy.data.objects).
    """
    holders_by_id: dict = {}
    for obj in bpy.data.objects:
        existing = _stored_id(obj)
        if existing:
            holders_by_id.setdefault(existing, []).append(obj)

    batch_names = {obj.name for obj in objects}
    taken = set(holders_by_id)
    resolved: dict = {}
    written: list = []

    def assign(obj: bpy.types.Object) -> None:
        remembered = _session_ids.get(obj.session_uid)
        new_id = remembered if remembered and remembered not in taken else uuid.uuid4().hex
        taken.add(new_id)
        obj[_ID_PROP] = new_id
        resolved[obj.name] = new_id
        written.append((obj, _ID_PROP, new_id))

    for existing_id, holders in holders_by_id.items():
        batch_holders = [obj for obj in holders if obj.name in batch_names]
        if not batch_holders:
            continue
        if len(holders) == 1:
            resolved[batch_holders[0].name] = existing_id
            continue
        known = [obj for obj in holders if _session_ids.get(obj.session_uid) == existing_id]
        winner = min(known or holders, key=lambda o: o.name)
        if winner.name in batch_names:
            resolved[winner.name] = existing_id
        for obj in batch_holders:
            if obj.name != winner.name:
                assign(obj)

    for obj in objects:
        if obj.name not in resolved:
            assign(obj)

    for obj in objects:
        _session_ids[obj.session_uid] = resolved[obj.name]
    link_journal.record(written)
    return resolved


def get_existing_id(obj: bpy.types.Object) -> Optional[str]:
    """Never generates one — safe for inventorying objects that were never
    sent (scene_graph.plan()'s delete diff)."""
    return _stored_id(obj) or _session_ids.get(obj.session_uid)


def _stored_id(obj: bpy.types.Object) -> Optional[str]:
    existing = obj.get(_ID_PROP)
    return existing if isinstance(existing, str) and existing else None
