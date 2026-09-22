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
    if isinstance(existing, str) and existing:
        return existing

    new_id = uuid.uuid4().hex
    obj[_ID_PROP] = new_id
    return new_id


def get_existing_id(obj: bpy.types.Object) -> Optional[str]:
    """Same lookup as `get_stable_id`, but never generates one — used to
    inventory which objects already carry an id, without side-effecting
    objects that were never sent (see `sent_ids.py`'s delete-diff)."""
    existing = obj.get(_ID_PROP)
    return existing if isinstance(existing, str) and existing else None
