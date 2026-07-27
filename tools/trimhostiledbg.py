"""What exactly makes the hand-mangled trimline unbuildable?

The new hostile-fixture contract requires the generator to refuse it with a
SPECIFIC user-facing reason. That reason has to name the real defect, so this
measures the mangled curve before designing the check:

  - closest non-adjacent self-approach (the cutter ribbon is +/- 1.5 mm, so
    two stretches under 3.0 mm apart merge it)
  - handle types and the stamped handle model (our own paths always leave
    FREE handles; anything else means the curve was edited outside them)
  - how far the present handles sit from a fresh C2 solve of the same control
    points, i.e. whether they are stale
  - which stage the build actually fails in

Writes trimhostiledbg_result.txt; quits Blender itself.
"""

import math
import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    trimline_ops,
)

OUT = r"C:\Projects\Blender Add-on Braces\trimhostiledbg_result.txt"
TRIES = {"n": 0}


def _sharpen_trimline():
    """Verbatim copy of the hostile fixture in rimresampletest."""
    perimeter = bpy.data.objects["Rigo Trim Perimeter"]
    points = perimeter.data.splines[0].bezier_points
    count = len(points)
    notch = count // 3
    for offset in (-1, 0, 1):
        point = points[(notch + offset) % count]
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    points[notch].co.z -= 0.015
    crowd = (2 * count) // 3
    anchor = points[crowd].co.copy()
    for offset in (1, 2):
        point = points[(crowd + offset) % count]
        direction = point.co - anchor
        if direction.length > 1e-9:
            point.co = anchor + direction.normalized() * (0.005 * offset)
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    perimeter.data.update_tag()


def _min_non_adjacent_gap(points):
    count = len(points)
    skip = max(4, count // 20)
    best, where = math.inf, (-1, -1)
    step = max(1, count // 600)
    for first in range(0, count, step):
        for second in range(0, count, step):
            if min((second - first) % count, (first - second) % count) < skip:
                continue
            gap = (points[first] - points[second]).length
            if gap < best:
                best, where = gap, (first, second)
    return best, where


def _handle_report(perimeter):
    points = perimeter.data.splines[0].bezier_points
    kinds = {}
    for point in points:
        for kind in (point.handle_left_type, point.handle_right_type):
            kinds[kind] = kinds.get(kind, 0) + 1
    return kinds


def _staleness(perimeter):
    """Distance from the present handles to a fresh C2 solve of the same points."""
    points = perimeter.data.splines[0].bezier_points
    present = [
        (point.handle_left.copy(), point.handle_right.copy()) for point in points
    ]
    coordinates = [point.co.copy() for point in points]
    tangents, spans = trimline_ops._periodic_c2_tangents(coordinates)
    worst = 0.0
    for index in range(len(points)):
        solved_right = coordinates[index] + tangents[index] * (spans[index] / 3.0)
        solved_left = coordinates[index] - tangents[index] * (spans[index - 1] / 3.0)
        worst = max(
            worst,
            (present[index][0] - solved_left).length,
            (present[index][1] - solved_right).length,
        )
    return worst * 1000.0


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = []
    try:
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        settings.trim_fillet_radius = 0.3
        settings.trim_fillet_segments = 8
        perimeter = bpy.data.objects["Rigo Trim Perimeter"]

        cutter_mm = curve_build_ops._CUTTER_HALF_DEPTH_M * 1000.0
        lines.append(
            f"cutter half depth={cutter_mm:.2f}mm -> stretches closer than "
            f"{2*cutter_mm:.2f}mm merge the ribbon"
        )
        lines.append(
            f"guard threshold C2_MIN_SELF_GAP_M="
            f"{trimline_ops.C2_MIN_SELF_GAP_M*1000:.2f}mm"
        )

        for label in ("HEALTHY", "MANGLED"):
            if label == "MANGLED":
                _sharpen_trimline()
            samples = curve_build_ops._curve_world_samples(perimeter)
            gap, where = _min_non_adjacent_gap(samples)
            lines.append("")
            lines.append(
                f"{label}: stamp={perimeter.get('rigo_trim_handle_model')!r} "
                f"handles={_handle_report(perimeter)}"
            )
            lines.append(
                f"  min non-adjacent self-gap={gap*1000:.3f}mm "
                f"(samples {where[0]} and {where[1]} of {len(samples)})"
            )
            lines.append(
                f"  handle staleness vs fresh C2 solve={_staleness(perimeter):.3f}mm"
            )
            try:
                result = bpy.ops.rigo.generate_curve_corset()
                error = ""
            except RuntimeError as exc:
                result, error = {"CANCELLED"}, str(exc).strip()
            lines.append(f"  generate={result} {error}")
            leftovers = sorted(
                obj.name
                for obj in bpy.data.objects
                if "Candidate" in obj.name
                or "Cutter" in obj.name
                or "Previous" in obj.name
            )
            lines.append(f"  leftover partial geometry={leftovers}")
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
