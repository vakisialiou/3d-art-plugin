"""Completes the Principled coat layer that Blender's glTF exporter leaves
incomplete (io_scene_gltf2's material/extensions/clearcoat.py):
KHR_materials_clearcoat carries Coat Weight, Coat Roughness and an image-fed
Coat Normal (material_bake.py bakes procedural ones first), but never Coat IOR
or Coat Tint, and omits clearcoatRoughnessFactor when it equals Blender's own
default 0.03 (BLENDER_COAT_ROUGHNESS) — glTF's default is 0.

A post-pass on the exported GLB's JSON chunk, per material that has
KHR_materials_clearcoat:
- `extras.coat = {ior, tint}` (tint scene-linear RGB), each only when its
  socket is flat — a linked one isn't carried, the browser falls back to
  Blender's default. GLTFLoader puts material extras on `material.userData`.
- an omitted clearcoatRoughnessFactor is written back explicitly.

Not a glTF2ExportUserExtension hook: io_scene_gltf2 discovers those only on
enabled add-ons (and would then also change the user's own File > Export).
"""

import json
import struct

import bpy

from .shader_bake import find_principled_surface

_CLEARCOAT = "KHR_materials_clearcoat"


def has_coat(principled: bpy.types.ShaderNodeBsdfPrincipled) -> bool:
    """Coat Weight linked or above 0 — when the exporter writes the extension
    (a linked weight once baked)."""
    weight = principled.inputs["Coat Weight"]
    return weight.is_linked or weight.default_value > 0.0


def collect_coat_extras(duplicate: bpy.types.Object) -> dict:
    """{material name: {"ior", "tint", "roughness"}} (flat sockets only) for
    every coated slot material. Run after the material preprocessing: the
    slots then hold the materials actually exported, and a glTF material keeps
    its Blender material's name (a bake copy's `.001` included)."""
    extras = {}
    for slot in duplicate.material_slots:
        material = slot.material
        if material is None or material.node_tree is None:
            continue
        principled = find_principled_surface(material)
        if principled is None or not has_coat(principled):
            continue
        coat = {}
        ior = principled.inputs["Coat IOR"]
        if not ior.is_linked:
            coat["ior"] = ior.default_value
        tint = principled.inputs["Coat Tint"]
        if not tint.is_linked:
            coat["tint"] = list(tint.default_value)[:3]
        roughness = principled.inputs["Coat Roughness"]
        if not roughness.is_linked:
            coat["roughness"] = roughness.default_value
        extras[material.name] = coat
    return extras


def inject_coat_extras(glb: bytes, coat_extras: dict) -> bytes:
    """Rewrites only the JSON chunk (the BIN chunk is copied verbatim); a GLB
    with nothing to add comes back byte-identical."""
    if not coat_extras:
        return glb
    magic, version, _length = struct.unpack_from("<4sII", glb, 0)
    json_length, json_type = struct.unpack_from("<I4s", glb, 12)
    if magic != b"glTF" or json_type != b"JSON":
        raise ValueError("not a GLB with a leading JSON chunk")
    gltf = json.loads(glb[20 : 20 + json_length])

    changed = False
    for material in gltf.get("materials", []):
        coat = coat_extras.get(material.get("name"))
        clearcoat = material.get("extensions", {}).get(_CLEARCOAT)
        if coat is None or clearcoat is None:
            continue
        layer = {key: coat[key] for key in ("ior", "tint") if key in coat}
        if layer:
            material.setdefault("extras", {})["coat"] = layer
            changed = True
        has_roughness = (
            "clearcoatRoughnessFactor" in clearcoat or "clearcoatRoughnessTexture" in clearcoat
        )
        if not has_roughness and "roughness" in coat:
            clearcoat["clearcoatRoughnessFactor"] = coat["roughness"]
            changed = True
    if not changed:
        return glb

    chunk = json.dumps(gltf, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    chunk += b" " * (-len(chunk) % 4)  # GLB chunks are 4-byte aligned, JSON padded with spaces
    body = struct.pack("<I4s", len(chunk), b"JSON") + chunk + glb[20 + json_length :]
    return struct.pack("<4sII", magic, version, 12 + len(body)) + body
