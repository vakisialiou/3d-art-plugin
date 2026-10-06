"""view_settings.curve_mapping → the tables Blender's GPU display shader reads.

The viewport never evaluates the R/G/B curves and the Combined curve one after
the other: BKE_curvemapping_premultiply bakes Combined into each channel's
CM_TABLE + 1 sample table, and the shader (gpu_shader_display_transform_frag.glsl
curvemap_evaluateF) interpolates that table, extrapolating past its ends.
Sampled here through CurveMapping.evaluate (BKE_curvemap_evaluateF, unclipped,
like the premultiply), in float32 like curvemap_make_table.

`tone` (FILMLIKE) isn't sent: the GPU path ignores it, so the viewport does too.
"""

import struct

import bpy

# CM_TABLE: a table holds CM_TABLE + 1 samples.
_CM_TABLE = 256
_COMBINED = 3


def _f32(value: float) -> float:
    return struct.unpack("f", struct.pack("f", value))[0]


def _table_span(mapping: bpy.types.CurveMapping, curve: bpy.types.CurveMap) -> tuple[float, float]:
    """curvemap_make_table's mintable/maxtable: the clip rect's x, widened to every point."""
    xs = [point.location[0] for point in curve.points]
    return (
        _f32(min([mapping.clip_min_x, *xs])),
        _f32(max([mapping.clip_max_x, *xs])),
    )


def _extend_slopes(
    mapping: bpy.types.CurveMapping, curve: bpy.types.CurveMap, lo: float, hi: float
) -> tuple[float, float]:
    """The slopes curvemap_calc_extend continues the curve with past its table:
    ext_in/ext_out's y/x, read back one unit outside the table, where
    BKE_curvemap_evaluateF extrapolates from the end samples."""
    slope_in = mapping.evaluate(curve, lo) - mapping.evaluate(curve, lo - 1.0)
    slope_out = mapping.evaluate(curve, hi + 1.0) - mapping.evaluate(curve, hi)
    return slope_in, slope_out


def _channel(mapping: bpy.types.CurveMapping, index: int) -> dict:
    curve = mapping.curves[index]
    combined = mapping.curves[_COMBINED]
    lo, hi = _table_span(mapping, curve)
    step = _f32(_f32(1.0 / _CM_TABLE) * _f32(hi - lo))
    table = [
        mapping.evaluate(combined, mapping.evaluate(curve, _f32(lo + _f32(step * sample))))
        for sample in range(_CM_TABLE + 1)
    ]
    slope_in, slope_out = _extend_slopes(mapping, curve, lo, hi)
    combined_lo, combined_hi = _table_span(mapping, combined)
    combined_in, combined_out = _extend_slopes(mapping, combined, combined_lo, combined_hi)
    return {
        "table": table,
        "range": _f32(1.0 / step),
        "first": [lo, table[0]],
        "last": [_f32(lo + _f32(step * _CM_TABLE)), table[_CM_TABLE]],
        # mul_v2_v2 of the two unit handle vectors: their slopes multiply.
        "slopeIn": slope_in * combined_in,
        "slopeOut": slope_out * combined_out,
    }


def build_curve_tables(mapping: bpy.types.CurveMapping) -> dict:
    mapping.initialize()
    return {
        "black": list(mapping.black_level),
        "white": list(mapping.white_level),
        "extrapolate": mapping.extend == "EXTRAPOLATED",
        "channels": [_channel(mapping, index) for index in range(3)],
    }
