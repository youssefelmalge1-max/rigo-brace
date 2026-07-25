"""Diagnostic: why does a second curve build differ after the seam fix?

Instruments `_projected_perimeter` to record, for each generate call, the
projected sample hash and the unwrapped angular span, then runs the operator
twice and reports what changed between the runs.
"""

import hashlib
import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    design_ops,
)

OUT = r"C:\Projects\Blender Add-on Braces\seamdeterminismdbg_result.txt"
TRIES = {"count": 0}
CALLS = []


def _write(lines):
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def _hash(values):
    return hashlib.sha256(repr(values).encode("utf-8")).hexdigest()[:16]


def _mesh_signature(obj):
    rows = sorted(
        tuple(round(c, 8) for c in v.co) for v in obj.data.vertices
    )
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()[:16]


_original = curve_build_ops._projected_perimeter


def _instrumented(base, perimeter):
    result = _original(base, perimeter)
    coordinates = [tuple(round(c, 10) for c in v) for v in result.coordinates]
    polygon = [(round(a, 10), round(z, 10)) for a, z in result.polygon]
    raw = [
        (round(a % (2.0 * 3.141592653589793), 10), round(z, 10))
        for a, z in result.polygon
    ]
    CALLS.append(
        {
            "n": len(result.coordinates),
            "coord_hash": _hash(coordinates),
            "poly_hash": _hash(polygon),
            "wrapped_hash": _hash(raw),
            "span": (result.theta_min, result.theta_max),
            "width": result.theta_max - result.theta_min,
        }
    )
    return result


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.ops.rigo, "generate_curve_corset") and TRIES["count"] < 30:
        return 0.1
    lines = []
    try:
        curve_build_ops._projected_perimeter = _instrumented
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        settings.corset_smooth = 5
        settings.trim_fillet_radius = 0.3
        settings.trim_fillet_segments = 8

        bpy.ops.rigo.generate_curve_corset()
        first_signature = _mesh_signature(bpy.data.objects["Rigo Corset"])
        bpy.ops.rigo.generate_curve_corset()
        second_signature = _mesh_signature(bpy.data.objects["Rigo Corset"])

        lines.append(f"projected_perimeter_calls={len(CALLS)}")
        for index, call in enumerate(CALLS):
            lines.append(
                f"  call{index}: n={call['n']} coord={call['coord_hash']} "
                f"poly={call['poly_hash']} wrapped={call['wrapped_hash']} "
                f"span=({call['span'][0]:.9f},{call['span'][1]:.9f}) "
                f"width={call['width']:.9f}"
            )
        if len(CALLS) >= 2:
            first, second = CALLS[0], CALLS[-1]
            lines.append(
                f"coords_identical={first['coord_hash'] == second['coord_hash']} "
                f"wrapped_identical={first['wrapped_hash'] == second['wrapped_hash']} "
                f"unwrapped_identical={first['poly_hash'] == second['poly_hash']} "
                f"span_delta_min={second['span'][0] - first['span'][0]:.12f} "
                f"span_delta_max={second['span'][1] - first['span'][1]:.12f}"
            )
        lines.append(
            f"mesh_first={first_signature} mesh_second={second_signature} "
            f"mesh_identical={first_signature == second_signature}"
        )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    _write(lines)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
