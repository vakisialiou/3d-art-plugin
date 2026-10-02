"""Stable per-object id, independent of the renameable `obj.name`. Stored as
a custom property, so it persists in the .blend across renames and reopens.
"""

import uuid
from typing import Optional

import bpy

_ID_PROP = "art3d_id"


def resolve_stable_ids(objects: list) -> dict:
    """Returns {obj.name: stable id} for one sync batch, generating ids where
    missing.

    Blender copies custom properties verbatim on duplicate/paste/append, so a
    duplicate can carry its original's art3d_id. All holders of an id are
    resolved together: the name that sorts first keeps it (Blender suffixes
    the duplicate's name, .001 etc., never the original's), the rest get
    fresh ids — deterministic regardless of call order.

    Keyed by `obj.name`, not `id(obj)`: bpy RNA wrappers aren't the same
    Python instance across access paths (`objects` vs bpy.data.objects).
    """
    holders_by_id: dict = {}
    for obj in bpy.data.objects:
        existing = get_existing_id(obj)
        if existing:
            holders_by_id.setdefault(existing, []).append(obj)

    batch_names = {obj.name for obj in objects}
    resolved: dict = {}

    for existing_id, holders in holders_by_id.items():
        batch_holders = [obj for obj in holders if obj.name in batch_names]
        if not batch_holders:
            continue
        if len(holders) == 1:
            resolved[batch_holders[0].name] = existing_id
            continue
        winner = min(holders, key=lambda o: o.name)
        if winner.name in batch_names:
            resolved[winner.name] = existing_id
        for obj in batch_holders:
            if obj.name != winner.name:
                new_id = uuid.uuid4().hex
                obj[_ID_PROP] = new_id
                resolved[obj.name] = new_id

    for obj in objects:
        if obj.name not in resolved:
            new_id = uuid.uuid4().hex
            obj[_ID_PROP] = new_id
            resolved[obj.name] = new_id

    return resolved


def get_existing_id(obj: bpy.types.Object) -> Optional[str]:
    """Never generates one — safe for inventorying objects that were never
    sent (operators.py's delete diff)."""
    existing = obj.get(_ID_PROP)
    return existing if isinstance(existing, str) and existing else None
