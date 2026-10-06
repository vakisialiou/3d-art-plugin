"""Material Preview's HDRI from the active World: the Environment Texture's
image if assigned (at most the scene's HDRI size), otherwise the Sky Texture
baked to an equirect. A Send uploads the bytes as a resource and names it in
`blender-world-hdri-sync`.

An image without pixels (its file missing or unreadable) raises Unreadable,
whose message is the HDRI row's note; the browser keeps the HDRI it has.
"""

import hashlib
import math
import os
import tempfile

import bpy

from .bake_device import render_device
from .constants import EXPORT_VERSION
from .object_key import hash_tree

_ENVIRONMENT_NODE_TYPE = "ShaderNodeTexEnvironment"
_SKY_NODE_TYPE = "ShaderNodeTexSky"

# 2:1 equirect ("1K HDRI"); a sky-only bake takes ~2 s, one step of a Send.
_BAKE_RESOLUTION_X = 1024
_BAKE_RESOLUTION_Y = 512
_BAKE_SAMPLES = 16


class Unreadable(Exception):
    """The Environment Texture's image has no pixels to send; the message
    names its file."""


def _find_node(world: bpy.types.World, bl_idname: str) -> bpy.types.ShaderNode | None:
    return next((node for node in world.node_tree.nodes if node.bl_idname == bl_idname), None)


def _file_name(image: bpy.types.Image) -> str:
    return bpy.path.basename(image.filepath) or image.name


def _missing_file(image: bpy.types.Image) -> str:
    """"Not found: <file>" when the image loads from a file that isn't there
    (known without loading it), else ""."""
    if image.source != "FILE" or image.packed_file is not None:
        return ""
    if os.path.isfile(bpy.path.abspath(image.filepath, library=image.library)):
        return ""
    return f"Not found: {_file_name(image)}"


def hdri_problem(scene: bpy.types.Scene) -> str:
    """Why the World's Environment Texture image won't send, as far as is
    known without loading it; "" when nothing is wrong. The HDRI row shows
    it before a Send."""
    world = scene.world
    if world is None or world.node_tree is None:
        return ""
    env_node = _find_node(world, _ENVIRONMENT_NODE_TYPE)
    if env_node is None or env_node.image is None:
        return ""
    return _missing_file(env_node.image)


def describe_world_hdri_source(context: bpy.types.Context) -> str | None:
    """Cheap, side-effect-free preview of what `build_hdri` would send; shared
    by the panel row and the Send job so they can't disagree. None means
    nothing to send.
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


# The last HDRIs built this session, by input key: an unchanged World is
# neither baked nor re-encoded again (a sky bake isn't byte-identical twice,
# so the browser couldn't tell it already has it).
_built: dict = {}


def build_hdri_cached(scene: bpy.types.Scene, max_width: int) -> tuple | None:
    """build_hdri(), reused while the World's node tree and images are unchanged."""
    world = scene.world
    if world is None or world.node_tree is None:
        return None
    digest = hashlib.sha256(f"hdri/{EXPORT_VERSION}/{max_width}".encode())
    hash_tree(digest, world.node_tree, set())
    key = digest.hexdigest()
    found = _built.get(key)
    if found is None:
        found = build_hdri(scene, max_width)
        if found is not None:
            _built.clear()
            _built[key] = found
    return found


def build_hdri(scene: bpy.types.Scene, max_width: int) -> tuple | None:
    """(name, Radiance HDR bytes) for Send HDRI: the Environment Texture's
    image, at most `max_width` wide (0 = its own size), else the Sky Texture
    baked to an equirect; None when the World has neither."""
    world = scene.world
    if world is None or world.node_tree is None:
        return None

    env_node = _find_node(world, _ENVIRONMENT_NODE_TYPE)
    if env_node is not None and env_node.image is not None:
        return env_node.image.name, _export_image_hdri(env_node.image, max_width)

    if _find_node(world, _SKY_NODE_TYPE) is not None:
        return f"{scene.name} Sky (baked)", _bake_sky_hdri(scene)

    return None


def _export_image_hdri(image: bpy.types.Image, max_width: int) -> bytes:
    # Always re-encoded to Radiance HDR so the browser needs only HDRLoader.
    # Saved from a copy: Image.save() honors the image's own file_format, and
    # scaling for Max Texture must not touch the user's image. The copy reads
    # the file again, so a missing or unreadable one leaves it without pixels.
    copy = image.copy()
    try:
        width, height = copy.size
        if not width or not height:
            raise Unreadable(_missing_file(image) or f"Can't read: {_file_name(image)}")
        if max_width and width > max_width:
            copy.scale(max_width, max(1, round(height * max_width / width)))
        copy.file_format = "HDR"
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "environment.hdr")
            copy.save(filepath=path, save_copy=True)
            with open(path, "rb") as hdr_file:
                return hdr_file.read()
    finally:
        bpy.data.images.remove(copy)


def _bake_sky_hdri(scene: bpy.types.Scene) -> bytes:
    # A procedural sky has no image, so render a world-only equirect capture.
    # Blender 5.2: the panorama type is `camera.data.panorama_type` (no
    # `.cycles` sub-struct) and defaults to FISHEYE_EQUISOLID, not equirect.
    # A sky is a smooth gradient: 1K stays enough whatever the HDRI size.
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
            with render_device(scene):
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

    return data
