"""Object keys: the name a Send gives an object's glb before exporting it, so
the browser can say "I have that" and the bake and export are skipped. The
key hashes everything the export reads — the evaluated mesh (geometry, UVs,
attributes), the modifier stack, every slot's material with its node trees
and images, a rig's bones and action — plus the add-on's export version and
the scene's Web Optimization signature. Two objects that would export the
same glb (copies of one mesh) get the same key and travel once.

Over-inclusion only costs a re-export; a missed input would leave a stale
object in the browser, which is why "Resend Everything" exists.

Geometry-nodes instances count too: each source mesh and its materials,
every instance's matrix (gltf_exporter sends them as GPU instances).

The same pass counts what the report shows: triangles, draw calls (one per
material used), world-space surface area (By Object Size bakes).
"""

import hashlib
import os
import uuid
from dataclasses import dataclass, field
from typing import Optional

import bpy
import numpy as np

from .constants import EXPORT_VERSION

# Types the glTF exporter (export_apply=True) evaluates to a mesh.
MESH_CONVERTIBLE_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}

_ID_SKIP = {
    "rna_type", "name", "name_full", "session_uid", "users", "use_fake_user", "use_extra_user",
    "is_editmode", "is_evaluated", "is_library_indirect", "is_missing", "is_runtime_data",
    "library", "library_weak_reference", "override_library", "preview", "tag", "original",
    "asset_data", "is_embedded_data", "id_type", "is_linked_packed", "is_grease_pencil",
}
_NODE_SKIP = _ID_SKIP | {
    "location", "location_absolute", "width", "width_hidden", "height", "dimensions", "select",
    "hide", "show_options", "show_preview", "show_texture", "label", "color", "use_custom_color",
    "parent", "warning_propagation", "inputs", "outputs", "internal_links", "type", "color_tag",
}
_SOCKET_SKIP = _ID_SKIP | {
    "hide", "hide_value", "show_expanded", "link_limit", "is_multi_input", "label", "description",
    "is_output", "is_linked", "is_unavailable", "is_icon_visible", "node", "links", "type",
    "display_shape", "pin_gizmo", "is_inactive",
}
_MAX_ITEMS = 512

# Packed image bytes hashed once a session: (name, size) → digest.
_packed_digests: dict = {}

_ATTRIBUTE_FIELDS = {
    "FLOAT": ("value", 1, np.float32),
    "INT": ("value", 1, np.int32),
    "BOOLEAN": ("value", 1, bool),
    "INT8": ("value", 1, np.int32),
    "FLOAT2": ("vector", 2, np.float32),
    "FLOAT_VECTOR": ("vector", 3, np.float32),
    "FLOAT_COLOR": ("color", 4, np.float32),
    "BYTE_COLOR": ("color", 4, np.float32),
    "INT32_2D": ("value", 2, np.int32),
    "INT16_2D": ("value", 2, np.int32),
    "QUATERNION": ("value", 4, np.float32),
}


@dataclass
class Info:
    key: str
    triangles: int = 0
    draw_calls: int = 0
    surface_area: float = 0.0
    materials: list = field(default_factory=list)  # names, for the unique-material count


def _text(digest, text: str) -> None:
    digest.update(text.encode("utf-8", "surrogatepass"))
    digest.update(b"\0")


def compute(obj: bpy.types.Object, depsgraph, signature: str) -> Optional[Info]:
    """The object's glb key and stats; None for an object without geometry."""
    if obj.type not in MESH_CONVERTIBLE_TYPES:
        return None
    digest = hashlib.sha256()
    _text(digest, f"art3d-glb/{EXPORT_VERSION}/{signature}/{obj.type}")
    info = Info(key="")
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        _hash_mesh(digest, mesh, obj, info)
    finally:
        evaluated.to_mesh_clear()
    seen: set = set()
    if any(modifier.type == "NODES" for modifier in obj.modifiers):
        _hash_instances(digest, obj, depsgraph, info, seen)
    for modifier in obj.modifiers:
        _text(digest, f"modifier:{modifier.type}")
        _hash_rna(digest, modifier, _ID_SKIP, 1, set())
    for slot in obj.material_slots:
        material = slot.material
        info.materials.append(material.name_full if material else "")
        _hash_material(digest, material, seen)
    armature = _armature_target(obj)
    if armature is not None:
        _hash_rig(digest, obj, armature)
    info.key = "g:" + digest.hexdigest()[:32]
    return info


def _hash_instances(digest, obj: bpy.types.Object, depsgraph, info: Info, seen: set) -> None:
    """Geometry-nodes instances, which export as GPU instances: each source's
    evaluated mesh and materials once, every instance's matrix relative to
    `obj` (moving `obj` itself doesn't change its glb)."""
    to_local = obj.matrix_world.inverted()
    counts: dict = {}
    matrices = []
    for instance in depsgraph.object_instances:
        if not instance.is_instance or instance.parent is None or instance.parent.original != obj:
            continue
        source = instance.object.original  # the instance itself is valid only while iterating
        name = source.name_full
        if name not in counts:
            counts[name] = [source, 0]
        counts[name][1] += 1
        matrices.append((name, to_local @ instance.matrix_world))
    for name in sorted(counts):
        source, count = counts[name]
        _text(digest, f"instance-source:{name}:{count}")
        part = Info(key="")
        evaluated = source.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            _hash_mesh(digest, mesh, source, part)
        finally:
            evaluated.to_mesh_clear()
        for slot in source.material_slots:
            _hash_material(digest, slot.material, seen)
        info.triangles += part.triangles * count
        info.draw_calls += part.draw_calls
        info.surface_area += part.surface_area * count
    for name, matrix in matrices:
        _text(digest, name)
        digest.update(np.array(matrix, dtype=np.float32).tobytes())


def _hash_mesh(digest, mesh, obj: bpy.types.Object, info: Info) -> None:
    if mesh is None or len(mesh.vertices) == 0:
        _text(digest, "empty")
        return
    loops = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loops)
    digest.update(loops.tobytes())
    count = len(mesh.polygons)
    for name, dtype in (("loop_start", np.int32), ("loop_total", np.int32), ("material_index", np.int32)):
        values = np.empty(count, dtype=dtype)
        mesh.polygons.foreach_get(name, values)
        digest.update(values.tobytes())
        if name == "material_index":
            info.draw_calls = int(np.unique(values).size) if count else 0
    for attribute in mesh.attributes:
        if attribute.name.startswith("."):
            continue  # internal state: selection, topology (hashed above)
        _text(digest, f"attribute:{attribute.name}/{attribute.domain}/{attribute.data_type}")
        spec = _ATTRIBUTE_FIELDS.get(attribute.data_type)
        if spec is None:
            continue
        name, width, dtype = spec
        values = np.empty(len(attribute.data) * width, dtype=dtype)
        attribute.data.foreach_get(name, values)
        digest.update(values.tobytes())
    for group in obj.vertex_groups:
        _text(digest, f"group:{group.index}:{group.name}")
    if _armature_target(obj) is not None:
        for vertex in mesh.vertices:
            for element in vertex.groups:
                _text(digest, f"{vertex.index}:{element.group}:{element.weight!r}")

    mesh.calc_loop_triangles()
    info.triangles = len(mesh.loop_triangles)
    if info.triangles:
        corners = np.empty(info.triangles * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get("vertices", corners)
        positions = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", positions)
        world = np.array(obj.matrix_world.to_3x3(), dtype=np.float32)
        points = positions.reshape(-1, 3) @ world.T
        triangles = points[corners.reshape(-1, 3)]
        cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
        info.surface_area = float(np.linalg.norm(cross, axis=1).sum() / 2)


def _hash_material(digest, material, seen: set) -> None:
    if material is None:
        _text(digest, "material:none")
        return
    # The exported material keeps this name (coat extras are matched by it).
    _text(digest, f"material:{material.name_full}")
    _hash_rna(digest, material, _ID_SKIP | {"node_tree", "grease_pencil", "paint_active_slot"}, 1, seen)
    if material.node_tree is not None:
        hash_tree(digest, material.node_tree, seen)


def hash_tree(digest, tree, seen: set) -> None:
    if tree.name_full in seen:
        _text(digest, f"tree:{tree.name_full}")
        return
    seen.add(tree.name_full)
    _text(digest, f"tree:{tree.bl_idname}:{tree.name_full}")
    for node in sorted(tree.nodes, key=lambda item: item.name):
        _text(digest, f"node:{node.bl_idname}:{node.name}:{node.mute}")
        _hash_rna(digest, node, _NODE_SKIP, 2, seen)
        for socket in list(node.inputs) + list(node.outputs):
            _text(digest, f"socket:{socket.identifier}:{socket.enabled}")
            _hash_rna(digest, socket, _SOCKET_SKIP, 0, seen)
    for link in tree.links:
        _text(
            digest,
            f"link:{link.from_node.name}.{link.from_socket.identifier}>"
            f"{link.to_node.name}.{link.to_socket.identifier}:{link.is_muted}:{link.is_valid}",
        )


def _hash_rna(digest, struct, skip: set, depth: int, seen: set) -> None:
    for prop in struct.bl_rna.properties:
        name = prop.identifier
        if name in skip or name.startswith("bl_"):
            continue
        try:
            value = getattr(struct, name)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
        if prop.type in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
            _text(digest, f"{name}={_plain(value)}")
        elif prop.type == "POINTER" and depth > 0:
            if value is None:
                _text(digest, f"{name}=None")
            elif isinstance(value, bpy.types.ID):
                _hash_id(digest, name, value, seen)
            else:
                _text(digest, f"{name}:")
                _hash_rna(digest, value, skip, depth - 1, seen)
        elif prop.type == "COLLECTION" and depth > 0:
            items = list(value)[:_MAX_ITEMS]
            _text(digest, f"{name}[{len(items)}]")
            for item in items:
                if isinstance(item, bpy.types.ID):
                    _hash_id(digest, name, item, seen)
                else:
                    _hash_rna(digest, item, skip, depth - 1, seen)


def _plain(value) -> str:
    if isinstance(value, (set, frozenset)):
        return repr(sorted(value))
    if hasattr(value, "__len__") and not isinstance(value, str):
        try:
            return repr([_plain(item) for item in value])
        except TypeError:
            return repr(value)
    return repr(value)


def _hash_id(digest, name: str, target, seen: set) -> None:
    if isinstance(target, bpy.types.Image):
        _hash_image(digest, target)
    elif isinstance(target, bpy.types.NodeTree):
        hash_tree(digest, target, seen)
    elif isinstance(target, bpy.types.Object):
        _text(digest, f"{name}=object:{target.name_full}:{_plain(target.matrix_world)}")
    else:
        _text(digest, f"{name}={type(target).__name__}:{target.name_full}")


def _hash_image(digest, image: bpy.types.Image) -> None:
    _text(
        digest,
        f"image:{image.name_full}:{image.source}:{tuple(image.size)}:"
        f"{image.colorspace_settings.name}:{image.alpha_mode}",
    )
    if image.is_dirty:
        _text(digest, f"unsaved:{uuid.uuid4().hex}")  # painted, not saved: always new
    elif image.packed_file is not None:
        _text(digest, _packed_digest(image))
    elif image.source in {"FILE", "SEQUENCE", "MOVIE", "TILED"}:
        path = bpy.path.abspath(image.filepath, library=image.library)
        try:
            stat = os.stat(path)
            _text(digest, f"file:{path}:{stat.st_size}:{stat.st_mtime_ns}")
        except OSError:
            _text(digest, f"missing:{path}")
    else:
        _text(
            digest,
            f"generated:{image.generated_type}:{tuple(image.generated_color)}:"
            f"{image.generated_width}x{image.generated_height}:{image.use_generated_float}",
        )


def _packed_digest(image: bpy.types.Image) -> str:
    packed = image.packed_file
    cache_key = (image.name_full, packed.size)
    found = _packed_digests.get(cache_key)
    if found is None:
        found = hashlib.sha256(packed.data).hexdigest()
        _packed_digests[cache_key] = found
    return found


def _armature_target(obj: bpy.types.Object) -> Optional[bpy.types.Object]:
    for modifier in obj.modifiers:
        if modifier.type == "ARMATURE" and modifier.object is not None:
            return modifier.object
    return None


def _action_fcurves(action) -> list:
    """F-curves of a legacy action or of every channelbag of a layered one."""
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        return list(legacy)
    curves = []
    for layer in getattr(action, "layers", []):
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                curves.extend(bag.fcurves)
    return curves


def _hash_rig(digest, obj: bpy.types.Object, armature: bpy.types.Object) -> None:
    # The skinned mesh keeps its matrix_local over the armature (bind pose).
    _text(digest, f"bind:{_plain(obj.matrix_local)}")
    for bone in armature.data.bones:
        parent = bone.parent.name if bone.parent else ""
        _text(digest, f"bone:{bone.name}:{parent}:{bone.use_deform}:{_plain(bone.matrix_local)}")
    action = armature.animation_data.action if armature.animation_data else None
    if action is None:
        return
    _text(digest, f"action:{action.name_full}")
    for curve in _action_fcurves(action):
        _text(digest, f"fcurve:{curve.data_path}:{curve.array_index}:{curve.mute}")
        points = curve.keyframe_points
        for name, width, dtype in (
            ("co", 2, np.float32),
            ("handle_left", 2, np.float32),
            ("handle_right", 2, np.float32),
            ("interpolation", 1, np.int32),
        ):
            values = np.empty(len(points) * width, dtype=dtype)
            points.foreach_get(name, values)
            digest.update(values.tobytes())
