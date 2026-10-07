"""Instances as instance sets. An object's geometry-nodes and particle
instances are grouped by what they show — a source object (Object Info "As
Instance", Collection Info, particles drawn as objects) or a mesh the node
tree made — and each group is one set: an entry drawing its group's mesh
once per placement.

A placement is a position, a rotation, a scale and a tint in the owner's
space, packed as the browser's `p:` blob (`Placements.encode` in skyray-web);
Blender's instances are untinted (white). A set of a source object sends the
glb that object's own entry would send and names the object in `instanceOf`,
so the browser links the sets of one source; a node-made mesh exports from a
temporary copy of the instance mesh. An owner without geometry of its own and
with one group is that set itself; otherwise its sets hang under it.
"""

import gzip
import struct
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

import bpy
import numpy as np

from . import object_key
from .object_id import get_existing_id
from .resource_pack import Pack, content_key

# 'PLC1' read as a little-endian uint32, then the count and the floats per
# placement: position 3, rotation quaternion (x, y, z, w) 4, scale 3, linear
# tint 3.
_MAGIC = 0x31434C50
_STRIDE = 13
_WHITE = (1.0, 1.0, 1.0)

# Every placement's tint, and the range a placement added in the browser takes one from.
TINT = ["#ffffff", "#ffffff"]

# Names the ids of sets and source objects derived from Blender names.
_NAMESPACE = uuid.UUID("5f0b8e52-6d1f-4c43-9a3e-2b7f1c9d0a64")


@dataclass
class Group:
    """One set: the instances of one source object, or of one node-made mesh."""

    ident: str  # stable within its owner: "o:<source name>" or "g<order>:<mesh name>"
    label: str  # the set's name: its source's, or "<owner> Instances" for a node-made mesh
    source: Optional[bpy.types.Object]  # None for a node-made mesh
    order: int = 0  # a node-made mesh: its place among the owner's node-made meshes
    floats: list = field(default_factory=list)  # placements, _STRIDE floats apiece
    info: Optional[object_key.Info] = None  # a node-made mesh: its key, hashed during the pass

    @property
    def count(self) -> int:
        return len(self.floats) // _STRIDE


@dataclass
class Blob:
    """A set's placements as uploaded."""

    key: str
    count: int
    data: bytes  # gzip-compressed


def is_owner(obj: bpy.types.Object) -> bool:
    """Whether `obj` may make instances: geometry nodes, or particles drawn as objects."""
    if obj.type not in object_key.MESH_CONVERTIBLE_TYPES:
        return False
    if any(modifier.type == "NODES" for modifier in obj.modifiers):
        return True
    return any(system.settings.render_type in {"OBJECT", "COLLECTION"} for system in obj.particle_systems)


def source_id(obj: bpy.types.Object) -> str:
    """The id `obj` goes by in `instanceOf`: its own once it has one, else one
    derived from its name (a source only instanced, or linked from a library)."""
    return get_existing_id(obj) or uuid.uuid5(_NAMESPACE, f"source/{obj.name_full}").hex


def set_id(owner_id: str, group: Group) -> str:
    return uuid.uuid5(_NAMESPACE, f"{owner_id}/set/{group.ident}").hex


def _mesh_materials(mesh, owner: bpy.types.Object) -> list:
    """A node-made mesh's materials (the originals, never their evaluated
    copies); with none set, its owner's, as the exporter takes them."""
    materials = [material.original if material is not None else None for material in mesh.materials]
    if not materials or (len(materials) == 1 and materials[0] is None):
        return [slot.material for slot in owner.material_slots]
    return materials


def gather(depsgraph, owners: dict, placing: set, signature: str) -> dict:
    """The instance groups of `owners` (name → object), in first-seen order:
    owner name → [Group]. Only the owners named in `placing` get placements
    and node-made mesh keys; the rest give their groups' idents alone (the
    deletion diff keeps their sets). One pass over the scene's instances."""
    groups: dict = {}  # owner name → {ident → Group}
    meshes: dict = {}  # owner name → {mesh pointer → ident}
    to_local: dict = {}
    for instance in depsgraph.object_instances:
        if not instance.is_instance or instance.parent is None:
            continue
        owner = owners.get(instance.parent.original.name)
        if owner is None:
            continue
        shown = instance.object
        if shown.original != owner:
            source = shown.original
            if source.type not in object_key.MESH_CONVERTIBLE_TYPES:
                continue
            ident = f"o:{source.name_full}"
            found = groups.setdefault(owner.name, {})
            group = found.get(ident)
            if group is None:
                group = found[ident] = Group(ident, source.name, source)
        else:
            mesh = shown.data
            if not isinstance(mesh, bpy.types.Mesh) or len(mesh.vertices) == 0:
                continue  # an instancer of nested instances, or not a mesh
            known = meshes.setdefault(owner.name, {})
            pointer = mesh.as_pointer()
            ident = known.get(pointer)
            found = groups.setdefault(owner.name, {})
            if ident is None:
                order = len(known)
                ident = known[pointer] = f"g{order}:{mesh.name}"
                label = f"{owner.name} Instances" + (f" {order + 1}" if order else "")
                group = found[ident] = Group(ident, label, None, order)
                if owner.name in placing:
                    group.info = object_key.geometry_info(
                        mesh, _mesh_materials(mesh, owner), owner, ident, signature
                    )
            group = found[ident]
        if owner.name not in placing:
            continue
        local = to_local.get(owner.name)
        if local is None:
            local = to_local[owner.name] = owner.matrix_world.inverted()
        location, rotation, scale = (local @ instance.matrix_world).decompose()
        group.floats.extend((
            location.x, location.y, location.z,
            rotation.x, rotation.y, rotation.z, rotation.w,
            scale.x, scale.y, scale.z,
            *_WHITE,
        ))
    return {name: list(found.values()) for name, found in groups.items()}


def blob(group: Group) -> Blob:
    """The group's placements as the browser stores them, keyed by their bytes."""
    data = struct.pack("<III", _MAGIC, group.count, _STRIDE) + np.asarray(group.floats, dtype="<f4").tobytes()
    return Blob(content_key("p", data), group.count, gzip.compress(data, compresslevel=6))


def export_mesh(owner: bpy.types.Object, group: Group, export: Callable[[bpy.types.Object], Pack]) -> Pack:
    """A node-made mesh, exported through a temporary object holding a copy
    of it (the instance's own mesh lives only while the instances are read)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    copy = None
    seen: set = set()
    for instance in depsgraph.object_instances:
        if not instance.is_instance or instance.parent is None or instance.parent.original != owner:
            continue
        shown = instance.object
        mesh = shown.data
        if shown.original != owner or not isinstance(mesh, bpy.types.Mesh) or len(mesh.vertices) == 0:
            continue
        pointer = mesh.as_pointer()
        if pointer in seen:
            continue
        if len(seen) == group.order:
            copy = mesh.copy()
            materials = _mesh_materials(mesh, owner)
            break
        seen.add(pointer)
    if copy is None:
        raise RuntimeError(f"{owner.name} no longer makes {group.label}")
    # Slot by slot, so each face keeps its material index.
    for index, material in enumerate(materials):
        if index < len(copy.materials):
            copy.materials[index] = material
        else:
            copy.materials.append(material)
    temporary = bpy.data.objects.new(group.label, copy)
    try:
        return export(temporary)
    finally:
        bpy.data.objects.remove(temporary)
        bpy.data.meshes.remove(copy)
