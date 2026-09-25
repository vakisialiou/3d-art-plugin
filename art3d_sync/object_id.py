"""Stable per-object id, independent of `obj.name` (which the user can freely
rename in Blender's outliner — that used to be the wire `id`, silently
orphaning the object on the browser side on every rename).

Stored as a custom property, so it persists in the .blend file across
renames and reopens; generated once, on first use.
"""

import uuid
from typing import Optional

import bpy

_ID_PROP = "art3d_id"


def resolve_stable_ids(objects: list) -> dict:
    """Resolves every object's stable id for one sync batch, all at once —
    the one entry point scene_graph.py uses for both an object's own `id`
    and a parent's `parentId` lookup.

    Blender copies custom properties verbatim on Shift+D/Alt+D duplicate,
    Ctrl+C/Ctrl+V paste, and File > Append/Link, so a fresh duplicate starts
    out carrying an exact copy of its original's art3d_id — a real,
    non-empty id is not proof it's actually unique. Resolving one object at
    a time (this function's own predecessor) checked that against the rest
    of the file correctly, but re-checking independently per object meant
    whichever of a colliding pair got resolved *first* silently kept the
    id, reassigning it away from the other even when that other was the
    long-lived original and the "winner" was a duplicate created moments
    earlier — the outcome depended on call order, not on which object
    actually owned the id's browser-side history.

    Resolved here as one batch instead: every object sharing an id is
    looked at together, and the tiebreaker is deterministic — the one whose
    name sorts first wins, since Blender always suffixes a duplicate's name
    (.001, .002, ...) and never touches the original's, so the bare name
    reliably sorts before any unrenamed copy of it.

    Keyed by `obj.name` (unique across bpy.data.objects, enforced by
    Blender itself) rather than Python object identity — bpy's RNA wrapper
    objects aren't guaranteed to be the same Python instance across two
    different access paths (this batch's own `objects` list vs the fresh
    bpy.data.objects pass below), so `id(obj)` isn't a safe map key for "the
    same Blender object" the way it would be for a plain Python object.

    One pass over bpy.data.objects up front (not one scan per object) also
    fixes a real O(n^2) cost on "Send All": the old per-object check scanned
    every object in the whole .blend file on every single call, and every
    object in a batch called it roughly twice (once for itself, once via a
    sibling's parentId lookup).
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
    """Never generates one — used to inventory which objects already carry
    an id, without side-effecting objects that were never sent (see
    `sent_ids.py`'s delete-diff, and `resolve_stable_ids` above)."""
    existing = obj.get(_ID_PROP)
    return existing if isinstance(existing, str) and existing else None
