"""Reads the active World's Environment Texture node (a real HDRI/equirect
image assigned by the user — distinct from world_sync.py's procedural
Nishita Sky Texture) into a plain-dict payload: name + base64-encoded
Radiance HDR bytes. Mirrors scene_graph.py's approach: gather into plain
data here, let the browser side decide how to apply it.
"""

import base64
import os
import tempfile

import bpy

_ENVIRONMENT_NODE_TYPE = "ShaderNodeTexEnvironment"


def build_world_hdri_sync(context: bpy.types.Context) -> dict | None:
    world = context.scene.world
    if world is None or world.node_tree is None:
        return None

    env_node = next(
        (node for node in world.node_tree.nodes if node.bl_idname == _ENVIRONMENT_NODE_TYPE),
        None,
    )
    if env_node is None or env_node.image is None:
        return None

    return {
        "name": env_node.image.name,
        "data": _export_image_hdri_base64(env_node.image),
    }


def _export_image_hdri_base64(image: bpy.types.Image) -> str:
    # Always re-encoded to Radiance HDR regardless of the source image's own
    # format (loaded .exr, packed, generated, whatever) — the browser side
    # only ever needs one decoder (HDRLoader) this way, confirmed against a
    # real running Blender (5.2.2): Image.save(file_format='HDR',
    # save_copy=True) produces a real "#?RADIANCE" file regardless of source.
    # `save_render()` was tried first and rejected — it uses the *scene's*
    # render image_settings (defaults to PNG), not the Image's own
    # file_format, confirmed the same way. `file_format` is a plain property
    # on the Image datablock, not scoped to this one save call, so it's
    # restored after — leaving it changed would be a real, surprising side
    # effect on the user's own World setup. `save_copy=True` never touches
    # `filepath`/`source` either (also confirmed) — this whole function is
    # read-only from the user's point of view.
    original_format = image.file_format
    image.file_format = "HDR"
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "environment.hdr")
            image.save(filepath=path, save_copy=True)
            with open(path, "rb") as hdr_file:
                data = hdr_file.read()
    finally:
        image.file_format = original_format
    return base64.b64encode(data).decode("ascii")
