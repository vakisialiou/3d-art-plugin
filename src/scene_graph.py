"""Which objects a Send covers and their `blender-sync` entries: one entry
per object, transform as explicit local-to-parent fields so the browser can
resolve hierarchy by id, geometry named by its object key (`glb`). A
Collection Instance adds an entry per object it shows (collection_copies.py),
geometry nodes and particles an entry per instance set (instance_sets.py).

matrix_local is sent as-is: the web scene is Z-up like Blender, no axis
conversion (see gltf_exporter.py).
"""

from dataclasses import dataclass, field
from typing import Optional

import bpy
from mathutils import Matrix

from . import collection_copies, instance_sets
from .object_id import get_existing_id, resolve_stable_ids
from .object_key import MESH_CONVERTIBLE_TYPES
from .sent_ids import get_previous_sent_ids


@dataclass
class Entry:
    # The object, a Collection Instance copy's source, or an instance set's owner.
    obj: bpy.types.Object
    id: str
    parent_id: Optional[str]
    # Has geometry to send. False for empties and for a hidden ancestor kept
    # only so its visible children land in the right place.
    exports: bool
    # A copy's or a set's own: its name ("": obj's), transform (None: obj's
    # matrix_local), the source the browser links it with.
    name: str = ""
    matrix: Optional[Matrix] = None
    instance_of: str = ""
    # An instance set: the group its glb comes from, and its placements.
    group: Optional[instance_sets.Group] = None
    placements: Optional[instance_sets.Blob] = None


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


def plan(
    scene: bpy.types.Scene, view_layer: bpy.types.ViewLayer, scope: str, skip_hidden: bool, signature: str
) -> Plan:
    """The entries a Send makes (stable ids assigned where missing) and the
    deletions it carries. Deletion is scene-wide, whatever the scope: an
    object sent before and no longer shown (deleted, or now disabled in
    renders with Skip Hidden on) goes from the browser, and so do the copies
    and sets of an instancer no longer making them."""
    shown = _shown(scene, view_layer, skip_hidden)
    objects = _covered(_named(scene, view_layer, scope), shown)
    objects.sort(key=_depth)
    names = {obj.name for obj in objects}
    ids = resolve_stable_ids(objects)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    owners = {obj.name: obj for obj in scene.objects if obj.name in shown and instance_sets.is_owner(obj)}
    groups = instance_sets.gather(depsgraph, owners, names, signature) if owners else {}
    result = Plan()
    for obj in objects:
        parent = obj.parent if obj.parent is not None and obj.parent.name in names else None
        entry = Entry(
            obj=obj,
            id=ids[obj.name],
            parent_id=ids[parent.name] if parent is not None else None,
            exports=obj.type in MESH_CONVERTIBLE_TYPES and obj.name in shown,
        )
        result.entries.append(entry)
        if entry.exports and obj.name in groups:
            result.entries.extend(_sets(entry, groups[obj.name], depsgraph))
        if obj.name in shown:
            result.entries.extend(_copies(entry, depsgraph, skip_hidden))

    kept = set()
    for obj in scene.objects:
        existing = get_existing_id(obj)
        if existing is None:
            continue
        if obj.name in shown or any(child.name in shown for child in obj.children_recursive):
            kept.add(existing)
        if obj.name in shown:
            kept.update(copy.id for copy in collection_copies.copies(obj, existing, depsgraph, skip_hidden))
            owned = groups.get(obj.name, ())
            if owned and not _is_own_set(obj, owned, depsgraph):
                kept.update(instance_sets.set_id(existing, group) for group in owned)
    result.deleted_ids = get_previous_sent_ids(scene) - kept
    result.deletions = [{"id": object_id, "action": "delete"} for object_id in sorted(result.deleted_ids)]
    return result


def _has_geometry(obj: bpy.types.Object, depsgraph) -> bool:
    """Whether `obj` shows geometry of its own, its instances aside (a
    particle emitter can hide itself in renders)."""
    if obj.is_instancer and not obj.show_instancer_for_render:
        return False
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    found = mesh is not None and len(mesh.vertices) > 0
    evaluated.to_mesh_clear()
    return found


def _is_own_set(obj: bpy.types.Object, groups: list, depsgraph) -> bool:
    """An owner without geometry of its own and with one group is that set itself."""
    return len(groups) == 1 and not _has_geometry(obj, depsgraph)


def _sets(owner: Entry, groups: list, depsgraph) -> list:
    """`owner`'s instance sets: the owner itself (_is_own_set), else an entry
    per set under it, the owner sending no glb without geometry of its own."""
    if _is_own_set(owner.obj, groups, depsgraph):
        _make_set(owner, groups[0])
        return []
    owner.exports = _has_geometry(owner.obj, depsgraph)
    entries = []
    for group in groups:
        entry = Entry(
            obj=owner.obj,
            id=instance_sets.set_id(owner.id, group),
            parent_id=owner.id,
            exports=True,
            name=group.label,
            matrix=Matrix.Identity(4),
        )
        _make_set(entry, group)
        entries.append(entry)
    return entries


def _make_set(entry: Entry, group: instance_sets.Group) -> None:
    entry.group = group
    entry.placements = instance_sets.blob(group)
    if group.source is not None:
        entry.instance_of = instance_sets.source_id(group.source)


def _copies(instancer: Entry, depsgraph, skip_hidden: bool) -> list:
    """A Collection Instance's copies as entries."""
    return [
        Entry(
            obj=copy.source,
            id=copy.id,
            parent_id=copy.parent_id,
            exports=copy.source.type in MESH_CONVERTIBLE_TYPES,
            name=copy.source.name,
            matrix=copy.matrix,
            instance_of=copy.instance_of,
        )
        for copy in collection_copies.copies(instancer.obj, instancer.id, depsgraph, skip_hidden)
    ]


def entry_payload(entry: Entry, glb_key: Optional[str]) -> dict:
    matrix = entry.matrix if entry.matrix is not None else entry.obj.matrix_local
    location, rotation, scale = matrix.decompose()
    payload = {
        "id": entry.id,
        # Display-only — may change between syncs, never used as a key.
        "name": entry.name or entry.obj.name,
        "parentId": entry.parent_id,
        "action": "update",
        # Blender's Object.type enum (rna_enum_object_type_items,
        # rna_object.cc), sent verbatim; a set draws a mesh.
        "type": "MESH" if entry.placements is not None else entry.obj.type,
        "position": [location.x, location.y, location.z],
        # Quaternion, not Euler: Euler order names ("XYZ" etc.) differ in
        # meaning between mathutils and three.js; quaternions don't.
        "rotation": [rotation.x, rotation.y, rotation.z, rotation.w],
        "scale": [scale.x, scale.y, scale.z],
        "glb": glb_key,
    }
    if entry.instance_of:
        payload["instanceOf"] = entry.instance_of
    if entry.placements is not None:
        payload["placements"] = {
            "key": entry.placements.key,
            "count": entry.placements.count,
            "tint": instance_sets.TINT,
        }
    return payload


def _copy_count(obj: bpy.types.Object, skip_hidden: bool, depth: int = 0) -> int:
    """How many copies a Collection Instance gives (collection_copies.copies), counted without the depsgraph."""
    collection = collection_copies.instanced(obj)
    if collection is None or depth >= collection_copies.MAX_DEPTH:
        return 0
    sources = collection_copies.objects(collection, skip_hidden)
    return len(sources) + sum(_copy_count(source, skip_hidden, depth + 1) for source in sources)


def summary(scene: bpy.types.Scene, view_layer: bpy.types.ViewLayer, scope: str, skip_hidden: bool) -> dict:
    """What a Send would cover, for the panel's rows: object (every entry the
    Objects row sends, whatever its type, a Collection Instance's copies
    too; instance sets show up only in the Send), material, and the light
    and camera counts the Lights and Camera rows send (data_objects()) — no
    ids assigned, nothing written."""
    named = _named(scene, view_layer, scope)
    shown = _shown(scene, view_layer, skip_hidden)
    objects = _covered(named, shown)
    meshes = [obj for obj in objects if obj.type in MESH_CONVERTIBLE_TYPES and obj.name in shown]
    materials = {slot.material.name_full for obj in meshes for slot in obj.material_slots if slot.material}
    return {
        "objects": len(objects) + sum(_copy_count(obj, skip_hidden) for obj in objects if obj.name in shown),
        "materials": len(materials),
        "lights": len(_of_type(named, shown, "LIGHT")),
        "cameras": len(_of_type(named, shown, "CAMERA")),
    }
