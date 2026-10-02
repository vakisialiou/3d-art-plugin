"""Material Preview's HDRI payload from the active World: the Environment
Texture's image if assigned, otherwise the Sky Texture baked to an equirect.
"""

import base64
import math
import os
import tempfile

import bpy

_ENVIRONMENT_NODE_TYPE = "ShaderNodeTexEnvironment"
_SKY_NODE_TYPE = "ShaderNodeTexSky"

# 2:1 equirect ("1K HDRI"); a sky-only bake takes ~2s, fine for a blocking button.
_BAKE_RESOLUTION_X = 1024
_BAKE_RESOLUTION_Y = 512
_BAKE_SAMPLES = 16


def _find_node(world: bpy.types.World, bl_idname: str) -> bpy.types.ShaderNode | None:
    return next((node for node in world.node_tree.nodes if node.bl_idname == bl_idname), None)


def describe_world_hdri_source(context: bpy.types.Context) -> str | None:
    """Cheap, side-effect-free preview of what `build_world_hdri_sync` would
    send; shared by the operator's poll() and the panel label so they can't
    disagree. None means nothing to send.
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
    # Always re-encoded to Radiance HDR so the browser needs only HDRLoader.
    # Image.save(save_copy=True) honors the Image's own file_format (unlike
    # save_render(), which uses the scene's render settings) and leaves
    # filepath/source alone; file_format persists on the Image, so restore it.
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
    # A procedural sky has no image, so render a world-only equirect capture.
    # Blender 5.2: the panorama type is `camera.data.panorama_type` (no
    # `.cycles` sub-struct) and defaults to FISHEYE_EQUISOLID, not equirect.
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
    # An unrotated camera looks down -Z, centering the equirect on the nadir.
    # +90 deg about X aims it at the horizon with +Z up — the standard layout
    # (center row = horizon, top = zenith).
    cam_obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)

    try:
        scene.camera = cam_obj
        render.engine = "CYCLES"
        render.resolution_x = _BAKE_RESOLUTION_X
        render.resolution_y = _BAKE_RESOLUTION_Y
        render.resolution_percentage = 100
        scene.cycles.samples = _BAKE_SAMPLES
        render.film_transparent = False
        # World-only capture: hide every object from the 360-degree camera.
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
