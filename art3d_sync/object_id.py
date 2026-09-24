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


def get_stable_id(obj: bpy.types.Object) -> str:
    existing = obj.get(_ID_PROP)
    if isinstance(existing, str) and existing and not _claimed_by_other(obj, existing):
        return existing

    new_id = uuid.uuid4().hex
    obj[_ID_PROP] = new_id
    return new_id


def _claimed_by_other(obj: bpy.types.Object, id_value: str) -> bool:
    """Blender copies custom properties verbatim on Shift+D/Alt+D duplicate,
    Ctrl+C/Ctrl+V paste, and File > Append/Link — so a duplicated object
    starts out carrying an exact copy of the original's art3d_id. Having a
    non-empty id is therefore not proof it's actually unique; every call has
    to reconfirm that against the rest of the file, so any of those
    operations gets a fresh id at the next sync instead of silently
    colliding with the object it was copied from."""
    return any(other is not obj and other.get(_ID_PROP) == id_value for other in bpy.data.objects)


def get_existing_id(obj: bpy.types.Object) -> Optional[str]:
    """Same lookup as `get_stable_id`, but never generates one — used to
    inventory which objects already carry an id, without side-effecting
    objects that were never sent (see `sent_ids.py`'s delete-diff)."""
    existing = obj.get(_ID_PROP)
    return existing if isinstance(existing, str) and existing else None
