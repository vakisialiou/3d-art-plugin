"""Builds Material Preview's HDRI payload from the active World: a real
image assigned to an Environment Texture node when present, otherwise a
baked equirectangular capture of the procedural Sky Texture (Nishita) —
see `describe_world_hdri_source` for the same detection used to preview
which of the two a send will use before the button is even pressed.
Mirrors scene_graph.py's approach: gather into plain data here, let the
browser side decide how to apply it.
"""

import base64
import math
import os
import tempfile

import bpy

_ENVIRONMENT_NODE_TYPE = "ShaderNodeTexEnvironment"
_SKY_NODE_TYPE = "ShaderNodeTexSky"

# 2:1 equirect, matches common "1K HDRI" convention — real Nishita-only bake
# takes ~2s at this size (measured live), fine for a synchronous button.
_BAKE_RESOLUTION_X = 1024
_BAKE_RESOLUTION_Y = 512
_BAKE_SAMPLES = 16


def _find_node(world: bpy.types.World, bl_idname: str) -> bpy.types.ShaderNode | None:
    return next((node for node in world.node_tree.nodes if node.bl_idname == bl_idname), None)


def describe_world_hdri_source(context: bpy.types.Context) -> str | None:
    """Cheap, side-effect-free classification of what `build_world_hdri_sync`
    would send right now — used by both the operator's `poll()` (to grey out
    the button) and the panel's status label (to say why/what before the
    click), so the two never drift apart from each other.
    Returns None when there is genuinely nothing to send.
    """
    world = context.scene.world
    if world is None or world.node_tree is None:
        return None

    env_node = _find_node(world, _ENVIRONMENT_NODE_TYPE)
    if env_node is not None and env_node.image is not None:
        return env_node.image.name

    if _find_node(world, _SKY_NODE_TYPE) is not None:
        return "Sky Texture (will bake)"

    return None


def build_world_hdri_sync(context: bpy.types.Context) -> dict | None:
    world = context.scene.world
    if world is None or world.node_tree is None:
        return None

    env_node = _find_node(world, _ENVIRONMENT_NODE_TYPE)
    if env_node is not None and env_node.image is not None:
        return {
            "name": env_node.image.name,
            "data": _export_image_hdri_base64(env_node.image),
        }

    if _find_node(world, _SKY_NODE_TYPE) is not None:
        return {
            "name": f"{context.scene.name} Sky (baked)",
            "data": _bake_sky_hdri_base64(context),
        }

    return None


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


def _bake_sky_hdri_base64(context: bpy.types.Context) -> str:
    # Nishita has no source image to re-encode — it's a procedural shader —
    # so the only way to get a real HDRI out of it is to actually render a
    # world-only equirectangular capture. Verified live against a running
    # Blender 5.2.2, not from memory or docs, because the obvious-looking
    # API is wrong on this version: the panorama type is `camera.data.
    # panorama_type` directly, NOT `camera.data.cycles.panorama_type` (that
    # `.cycles` sub-struct doesn't exist here). It also defaults to
    # FISHEYE_EQUISOLID, not equirectangular — confirmed by rendering both
    # and comparing corner pixels: fisheye leaves the frame corners black
    # (circular image inscribed in the frame), equirect fills every pixel.
    # Getting this wrong would have silently shipped fisheye-distorted
    # "HDRIs" that still decode and render, just with the wrong projection.
    scene = context.scene
    render = scene.render

    original_camera = scene.camera
    original_engine = render.engine
    original_res_x = render.resolution_x
    original_res_y = render.resolution_y
    original_res_pct = render.resolution_percentage
    original_samples = scene.cycles.samples
    original_film_transparent = render.film_transparent
    original_file_format = render.image_settings.file_format
    original_filepath = render.filepath
    original_hide_render = {obj: obj.hide_render for obj in scene.objects}

    cam_data = bpy.data.cameras.new("Art3dHdriBakeCam")
    cam_data.type = "PANO"
    cam_data.panorama_type = "EQUIRECTANGULAR"
    cam_obj = bpy.data.objects.new("Art3dHdriBakeCam", cam_data)
    scene.collection.objects.link(cam_obj)
    cam_obj.location = (0.0, 0.0, 0.0)
    # An un-rotated Blender camera points down local -Z with +Y as its
    # "up" — for this PANO camera that puts the image's *center* (its
    # forward direction) facing straight down, not at the horizon. Nishita
    # has no ground model, so straight-down renders flat black; the result
    # was a black disc filling most of the frame regardless of any Sky
    # Texture setting, confirmed live by comparing renders before/after this
    # rotation. Rotating 90 deg about X points the camera's forward at the
    # horizon and its up at world +Z, matching the standard equirect HDRI
    # convention (center row = horizon, top = zenith, bottom = nadir).
    cam_obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)

    try:
        scene.camera = cam_obj
        render.engine = "CYCLES"
        render.resolution_x = _BAKE_RESOLUTION_X
        render.resolution_y = _BAKE_RESOLUTION_Y
        render.resolution_percentage = 100
        scene.cycles.samples = _BAKE_SAMPLES
        render.film_transparent = False
        # World-only capture — every other object would otherwise show up
        # in a 360-degree camera and has nothing to do with an HDRI export.
        for obj in scene.objects:
            if obj is not cam_obj:
                obj.hide_render = True

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "world_bake.hdr")
            render.image_settings.file_format = "HDR"
            render.filepath = path
            bpy.ops.render.render(write_still=True)
            with open(path, "rb") as hdr_file:
                data = hdr_file.read()
    finally:
        scene.camera = original_camera
        render.engine = original_engine
        render.resolution_x = original_res_x
        render.resolution_y = original_res_y
        render.resolution_percentage = original_res_pct
        scene.cycles.samples = original_samples
        render.film_transparent = original_film_transparent
        render.image_settings.file_format = original_file_format
        render.filepath = original_filepath
        for obj, hidden in original_hide_render.items():
            obj.hide_render = hidden
        bpy.data.objects.remove(cam_obj, do_unlink=True)
        bpy.data.cameras.remove(cam_data)

    return base64.b64encode(data).decode("ascii")
