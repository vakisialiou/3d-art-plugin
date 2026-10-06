"""Which objects a Send covers and their `blender-sync` entries: one entry
per object, transform as explicit local-to-parent fields so the browser can
resolve hierarchy by id, geometry named by its object key (`glb`).

matrix_local is sent as-is: the web scene is Z-up like Blender, no axis
conversion (see gltf_exporter.py).
"""

from dataclasses import dataclass, field
from typing import Optional

import bpy

from .object_id import get_existing_id, resolve_stable_ids
from .object_key import MESH_CONVERTIBLE_TYPES
from .sent_ids import get_previous_sent_ids


@dataclass
class Entry:
    obj: bpy.types.Object
    id: str
    parent_id: Optional[str]
    # Has geometry to send. False for empties and for a hidden ancestor kept
    # only so its visible children land in the right place.
    exports: bool


@dataclass
class Plan:
    entries: list = field(default_factory=list)  # parents before children
    deletions: list = field(default_factory=list)  # `action: 'delete'` entries
    deleted_ids: set = field(default_factory=set)


def renderable_names(scene: bpy.types.Scene, view_layer: bpy.types.ViewLayer) -> set:
    """Objects a render would show: not disabled in renders themselves, in at
    least one collection that is neither excluded nor disabled in renders
    (all the way up)."""
    visible: set = set()

    def walk(layer_collection, parent_visible: bool) -> None:
        collection = layer_collection.collection
        shown = parent_visible and not layer_collection.exclude and not collection.hide_render
        if shown:
            visible.add(collection.name_full)
        for child in layer_collection.children:
            walk(child, shown)

    walk(view_layer.layer_collection, True)
    return {
        obj.name
        for obj in scene.objects
        if not obj.hide_render and any(collection.name_full in visible for collection in obj.users_collection)
    }


def selected_objects(view_layer: bpy.types.ViewLayer) -> list:
    return [obj for obj in view_layer.objects if obj.select_get(view_layer=view_layer)]


def _with_descendants(scene: bpy.types.Scene, roots: list) -> list:
    """`roots` and every scene object under them — one pass over the scene,
    not Object.children_recursive per root (each of those scans it all)."""
    children: dict = {}
    for obj in scene.objects:
        if obj.parent is not None:
            children.setdefault(obj.parent.name, []).append(obj)
    result = list(roots)
    seen = {obj.name for obj in roots}
    pending = list(roots)
    while pending:
        for child in children.get(pending.pop().name, ()):
            if child.name not in seen:
                seen.add(child.name)
                result.append(child)
                pending.append(child)
    return result


def _depth(obj: bpy.types.Object) -> int:
    depth = 0
    while obj.parent is not None:
        depth += 1
        obj = obj.parent
    return depth


def _named(scene, view_layer, scope: str) -> list:
    """The objects a scope names. Selected names what's selected with
    everything under it — a rig's meshes, a group's members."""
    if scope == "SELECTED":
        return _with_descendants(scene, selected_objects(view_layer))
    return list(scene.objects)


def _shown(scene, view_layer, skip_hidden: bool) -> set:
    """Names of the objects that count as shown: with Skip Hidden, those a render shows."""
    return renderable_names(scene, view_layer) if skip_hidden else {obj.name for obj in scene.objects}


def _covered(named: list, shown: set) -> list:
    """The shown objects of `named` with their ancestors, shown or not, so the
    hierarchy always resolves."""
    collected: dict = {}
    for obj in named:
        if obj.name not in shown:
            continue
        current = obj
        while current is not None and current.name not in collected:
            collected[current.name] = current
            current = current.parent
    return list(collected.values())


def _of_type(named: list, shown: set, object_type: str) -> list:
    return [obj for obj in named if obj.type == object_type and obj.name in shown]


def data_objects(scene, view_layer, scope: str, skip_hidden: bool, object_type: str) -> list:
    """The lights or cameras (`object_type`) whose data a Send carries: the
    shown ones among the objects the scope names, as the Objects row covers
    them. An ancestor added only for the hierarchy carries none: a render
    shows nothing of it."""
    return _of_type(_named(scene, view_layer, scope), _shown(scene, view_layer, skip_hidden), object_type)


def plan(scene: bpy.types.Scene, view_layer: bpy.types.ViewLayer, scope: str, skip_hidden: bool) -> Plan:
    """The entries a Send makes (stable ids assigned where missing) and the
    deletions it carries. Deletion is scene-wide, whatever the scope: an
    object sent before and no longer shown (deleted, or now disabled in
    renders with Skip Hidden on) goes from the browser."""
    shown = _shown(scene, view_layer, skip_hidden)
    objects = _covered(_named(scene, view_layer, scope), shown)
    objects.sort(key=_depth)
    names = {obj.name for obj in objects}
    ids = resolve_stable_ids(objects)
    result = Plan()
    for obj in objects:
        parent = obj.parent if obj.parent is not None and obj.parent.name in names else None
        result.entries.append(
            Entry(
                obj=obj,
                id=ids[obj.name],
                parent_id=ids[parent.name] if parent is not None else None,
                exports=obj.type in MESH_CONVERTIBLE_TYPES and obj.name in shown,
            )
        )

    kept = set()
    for obj in scene.objects:
        existing = get_existing_id(obj)
        if existing is None:
            continue
        if obj.name in shown or any(child.name in shown for child in obj.children_recursive):
            kept.add(existing)
    result.deleted_ids = get_previous_sent_ids(scene) - kept
    result.deletions = [{"id": object_id, "action": "delete"} for object_id in sorted(result.deleted_ids)]
    return result


def entry_payload(entry: Entry, glb_key: Optional[str]) -> dict:
    location, rotation, scale = entry.obj.matrix_local.decompose()
    return {
        "id": entry.id,
        # Display-only — may change between syncs, never used as a key.
        "name": entry.obj.name,
        "parentId": entry.parent_id,
        "action": "update",
        # Blender's Object.type enum (rna_enum_object_type_items,
        # rna_object.cc), sent verbatim.
        "type": entry.obj.type,
        "position": [location.x, location.y, location.z],
        # Quaternion, not Euler: Euler order names ("XYZ" etc.) differ in
        # meaning between mathutils and three.js; quaternions don't.
        "rotation": [rotation.x, rotation.y, rotation.z, rotation.w],
        "scale": [scale.x, scale.y, scale.z],
        "glb": glb_key,
    }


def summary(scene: bpy.types.Scene, view_layer: bpy.types.ViewLayer, scope: str, skip_hidden: bool) -> dict:
    """What a Send would cover, for the panel's rows: object (every entry the
    Objects row sends, whatever its type), material, and the light and camera
    counts the Lights and Camera rows send (data_objects()) — no ids
    assigned, nothing written."""
    named = _named(scene, view_layer, scope)
    shown = _shown(scene, view_layer, skip_hidden)
    objects = _covered(named, shown)
    meshes = [obj for obj in objects if obj.type in MESH_CONVERTIBLE_TYPES and obj.name in shown]
    materials = {slot.material.name_full for obj in meshes for slot in obj.material_slots if slot.material}
    return {
        "objects": len(objects),
        "materials": len(materials),
        "lights": len(_of_type(named, shown, "LIGHT")),
        "cameras": len(_of_type(named, shown, "CAMERA")),
    }
