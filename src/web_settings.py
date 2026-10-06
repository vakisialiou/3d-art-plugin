"""Web Optimization: per-scene settings for what a Send turns the scene
into — texture and bake sizes, HDRI size, image format, mesh compression,
whether objects disabled in renders go. Stored on the Scene (the .blend), so
each scene keeps its own target. Every Send reads one frozen copy (Snapshot),
and the copy's signature is part of each object's key: changing a setting
re-exports instead of reusing what the browser already has.
"""

import math
from dataclasses import astuple, dataclass

import bpy

_ORIGINAL = "ORIGINAL"


@dataclass(frozen=True)
class Snapshot:
    max_texture: int  # 0 = original size
    bake_size: int  # 0 = by object size (texel_density)
    texel_density: float  # pixels per meter, for bake_size 0
    hdri_width: int  # 0 = original size
    texture_format: str  # "WEBP" | "PNG"
    mesh_compression: str  # "MESHOPT" | "NONE"
    skip_hidden: bool

    def signature(self) -> str:
        """Everything that changes an exported glb; HDRI and visibility don't."""
        return f"{self.max_texture}/{self.bake_size}/{self.texel_density:g}/{self.texture_format}/{self.mesh_compression}"

    def bake_size_for(self, surface_area: float) -> int:
        """The bake resolution for an object of `surface_area` square meters:
        the fixed size, or the next power of two at the texel density, both
        capped by max_texture (and kept between 64 and 4096)."""
        if self.bake_size:
            size = self.bake_size
        else:
            side = math.sqrt(max(surface_area, 0.0)) * self.texel_density
            size = 1 << max(6, min(12, math.ceil(math.log2(max(side, 1.0)))))
        if self.max_texture:
            size = min(size, self.max_texture)
        return size

    def key(self) -> tuple:
        return astuple(self)


def _size_items(values: tuple, original: str) -> list:
    items = [(str(value), str(value), f"Up to {value} × {value} pixels") for value in values]
    items.append((_ORIGINAL, "Original", original))
    return items


class ART3D_WebSettings(bpy.types.PropertyGroup):
    max_texture: bpy.props.EnumProperty(
        name="Max Texture",
        description="Largest texture side sent to the web; bigger images are scaled down for the export only",
        items=_size_items((512, 1024, 2048, 4096), "Images keep their own size"),
        default="2048",
    )
    bake_size: bpy.props.EnumProperty(
        name="Bake Size",
        description="Resolution of the textures baked from procedural materials",
        items=[
            ("AUTO", "By Object Size", "Bigger objects get bigger textures, at the texel density below"),
            ("256", "256", "256 × 256 pixels"),
            ("512", "512", "512 × 512 pixels"),
            ("1024", "1024", "1024 × 1024 pixels"),
            ("2048", "2048", "2048 × 2048 pixels"),
        ],
        default="512",
    )
    texel_density: bpy.props.FloatProperty(
        name="Density",
        description="Pixels per meter of surface for By Object Size bakes",
        default=256.0,
        min=16.0,
        max=4096.0,
        subtype="NONE",
    )
    hdri_size: bpy.props.EnumProperty(
        name="HDRI",
        description="Width of the environment image sent by Send HDRI",
        items=[
            ("1024", "1K", "1024 × 512"),
            ("2048", "2K", "2048 × 1024"),
            ("4096", "4K", "4096 × 2048"),
            (_ORIGINAL, "Original", "The environment image's own size"),
        ],
        default="2048",
    )
    texture_format: bpy.props.EnumProperty(
        name="Textures",
        description="Image format of the textures sent to the web",
        items=[
            ("WEBP", "WebP", "Several times smaller than PNG; slight compression"),
            ("PNG", "PNG", "Lossless, much heavier"),
        ],
        default="WEBP",
    )
    mesh_compression: bpy.props.EnumProperty(
        name="Meshes",
        description="Geometry compression for the web",
        items=[
            ("MESHOPT", "Meshopt", "Several times smaller; the browser unpacks it almost instantly"),
            ("NONE", "No Compression", "Raw geometry"),
        ],
        default="MESHOPT",
    )
    skip_hidden: bpy.props.BoolProperty(
        name="Skip Hidden",
        description="Don't send objects disabled in renders (boolean cutters, references)",
        default=True,
    )


def _size(value: str) -> int:
    return 0 if value == _ORIGINAL else int(value)


def snapshot(scene: bpy.types.Scene) -> Snapshot:
    settings = scene.art3d_web
    return Snapshot(
        max_texture=_size(settings.max_texture),
        bake_size=0 if settings.bake_size == "AUTO" else int(settings.bake_size),
        texel_density=float(settings.texel_density),
        hdri_width=_size(settings.hdri_size),
        texture_format=settings.texture_format,
        mesh_compression=settings.mesh_compression,
        skip_hidden=bool(settings.skip_hidden),
    )


def register() -> None:
    bpy.utils.register_class(ART3D_WebSettings)
    bpy.types.Scene.art3d_web = bpy.props.PointerProperty(type=ART3D_WebSettings)


def unregister() -> None:
    del bpy.types.Scene.art3d_web
    bpy.utils.unregister_class(ART3D_WebSettings)
