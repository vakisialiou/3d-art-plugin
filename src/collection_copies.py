"""Collection Instances as linked copies. Each object of an instanced
collection — and of the collections inside it — becomes an entry of its own
under the instancing empty, where the instance shows it, sending the glb its
source would send and naming the source in `instanceOf`, so the browser links
the copies of one source. A Collection Instance inside the collection gives
copies of copies.

A copy's id comes from its parent's id and its source's name, so it stays the
same from Send to Send while the source keeps its name. Only geometry,
empties and armatures are copied; lights, cameras and other data-only
objects inside an instanced collection are left out.
"""

import uuid
from dataclasses import dataclass
from typing import Optional

import bpy
from mathutils import Matrix

from .instance_sets import source_id
from .object_key import MESH_CONVERTIBLE_TYPES

_COPIED_TYPES = MESH_CONVERTIBLE_TYPES | {"EMPTY", "ARMATURE"}
# Collection Instances inside instanced collections, deeper than this, are left out.
MAX_DEPTH = 8

_NAMESPACE = uuid.UUID("0c6f3a8e-2d5b-4f1e-9b7a-6e4d2c1a8f35")


@dataclass
class Copy:
    source: bpy.types.Object
    id: str
    parent_id: str
    matrix: Matrix  # local to the parent copy, or to the instancing empty
    instance_of: str


def instanced(obj: bpy.types.Object) -> Optional[bpy.types.Collection]:
    """The collection `obj` instances, if it is a Collection Instance."""
    if obj.instance_type == "COLLECTION":
        return obj.instance_collection
    return None


def objects(collection: bpy.types.Collection, skip_hidden: bool) -> list:
    """`collection`'s objects and those of the collections inside it, once
    each; with `skip_hidden`, what a render leaves out stays out."""
    found: dict = {}

    def walk(current: bpy.types.Collection) -> None:
        for obj in current.objects:
            if obj.type in _COPIED_TYPES and not (skip_hidden and obj.hide_render):
                found.setdefault(obj.name_full, obj)
        for child in current.children:
            if not (skip_hidden and child.hide_render):
                walk(child)

    walk(collection)
    return list(found.values())


def copies(empty: bpy.types.Object, empty_id: str, depsgraph, skip_hidden: bool, depth: int = 0) -> list:
    """The copies a Collection Instance shows, parents before children. Read
    from the evaluated sources: an object only instanced has no up-to-date
    transform of its own."""
    collection = instanced(empty)
    if collection is None or depth >= MAX_DEPTH:
        return []
    found = objects(collection, skip_hidden)
    names = {obj.name_full for obj in found}
    ids = {obj.name_full: uuid.uuid5(_NAMESPACE, f"{empty_id}/{obj.name_full}").hex for obj in found}
    offset = Matrix.Translation(-collection.instance_offset)

    def depth_of(obj: bpy.types.Object) -> int:
        count = 0
        while obj.parent is not None and obj.parent.name_full in names:
            count += 1
            obj = obj.parent
        return count

    result: list = []
    for source in sorted(found, key=lambda obj: (depth_of(obj), obj.name_full)):
        parent = source.parent if source.parent is not None and source.parent.name_full in names else None
        evaluated = source.evaluated_get(depsgraph)
        copy = Copy(
            source=source,
            id=ids[source.name_full],
            parent_id=ids[parent.name_full] if parent is not None else empty_id,
            # A source parented outside the collection is placed by its world matrix, as the instance shows it.
            matrix=evaluated.matrix_local.copy() if parent is not None else offset @ evaluated.matrix_world,
            instance_of=source_id(source),
        )
        result.append(copy)
        result.extend(copies(source, copy.id, depsgraph, skip_hidden, depth + 1))
    return result
