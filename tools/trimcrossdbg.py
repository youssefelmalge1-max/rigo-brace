"""Does a self-crossing trimline produce the "non-manifold edge(s)" refusal?

Also measures how much clearance a healthy trimline actually has, so a
pre-flight check could be given a defensible threshold. The cutter is
extruded +/- _CUTTER_HALF_DEPTH_M along the surface normal, so two stretches
of trimline passing closer than twice that merge the cutter into a
self-touching surface even without a true crossing.
"""

import math
import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import curve_build_ops  # noqa: E402

OUT = r"C:\Projects\Blender Add-on Braces\trimcrossdbg_result.txt"
TRIES = {"n": 0}


def _min_non_adjacent_gap(points, skip):
    """Closest approach between stretches far apart ALONG the curve.

    The curve is closed, so separation has to be circular: the first version
    of this compared samples 3 and 2014 of 2016 - five apart around the wrap -
    and reported their spacing as if it were a near-miss between two
    different stretches.
    """
    count = len(points)
    best = (math.inf, -1, -1)
    step = max(1, count // 600)
    for i in range(0, count, step):
        for j in range(0, count, step):
            separation = min((j - i) % count, (i - j) % count)
            if separation < skip:
                continue
            gap = (points[i] - points[j]).length
            if gap < best[0]:
                best = (gap, i, j)
    return best


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = []
    try:
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        cutter_mm = curve_build_ops._CUTTER_HALF_DEPTH_M * 1000.0
        lines.append(
            f"cutter half depth = {cutter_mm:.2f} mm "
            f"(two stretches closer than {2*cutter_mm:.2f} mm can merge)"
        )

        perimeter = bpy.data.objects["Rigo Trim Perimeter"]
        samples = curve_build_ops._curve_world_samples(perimeter)
        skip = max(4, len(samples) // 20)
        gap, first, second = _min_non_adjacent_gap(samples, skip)
        lines.append(
            f"HEALTHY trimline: samples={len(samples)} "
            f"min non-adjacent gap={gap*1000:.3f} mm "
            f"(between sample {first} and {second})"
        )

        result = bpy.ops.rigo.generate_curve_corset()
        lines.append(f"HEALTHY build: {result}")

        # Force a self-crossing: drag one control point across the curve to
        # the far side of a distant stretch.
        points = perimeter.data.splines[0].bezier_points
        count = len(points)
        source = count // 4
        target = (source + count // 2) % count
        for offset in (-1, 0, 1):
            point = points[(source + offset) % count]
            point.handle_left_type = "AUTO"
            point.handle_right_type = "AUTO"
        original = points[source].co.copy()
        points[source].co = points[target].co.copy()
        perimeter.data.update_tag()
        moved = (points[source].co - original).length
        lines.append(
            f"\nCROSSED trimline: control point {source} moved "
            f"{moved*1000:.1f} mm onto point {target}"
        )
        samples = curve_build_ops._curve_world_samples(perimeter)
        gap, first, second = _min_non_adjacent_gap(samples, skip)
        lines.append(
            f"  min non-adjacent gap={gap*1000:.3f} mm "
            f"(between sample {first} and {second})"
        )
        try:
            crossed = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            crossed, error = {"CANCELLED"}, str(exc).strip()
        lines.append(f"  build: {crossed}")
        lines.append(f"  error: {error}")
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
