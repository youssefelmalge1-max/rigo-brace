"""Why does Generate fail after the Smooth Trimline Brush?

trimqualitytest's second fixture brushes the perimeter and then generates; the
generate produced no corset and the test crashed reading it. Two candidate
causes: the stale-handle pre-flight refusing a legitimately brushed curve, or
an unrelated build failure. This reports the actual message, plus the stamp and
staleness the pre-flight sees, so the cause is read rather than guessed.
"""

import sys
import traceback

import bpy
from mathutils.bvhtree import BVHTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    trimline_ops,
)
from bl_ext.user_default.rigo_brace.operators.trimline_ops import (  # noqa: E402
    _TrimBrushConfig,
    _smooth_trim_controls_local,
)

OUT = r"C:\Projects\Blender Add-on Braces\trimbrushgendbg_result.txt"
TRIES = {"n": 0}


def _state(perimeter, label, lines):
    model = str(perimeter.get("rigo_trim_handle_model", ""))
    spline = perimeter.data.splines[0]
    stale = trimline_ops.handles_are_stale(perimeter)
    kinds = {}
    for point in spline.bezier_points:
        for kind in (point.handle_left_type, point.handle_right_type):
            kinds[kind] = kinds.get(kind, 0) + 1
    reason = curve_build_ops._stale_handle_reason(perimeter)
    lines.append(f"{label}: stamp={model!r} stale={stale} handles={kinds}")
    lines.append(f"    pre-flight verdict={reason!r}")


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = []
    try:
        scan, settings = prepare_reference_design()
        perimeter = bpy.data.objects["Rigo Trim Perimeter"]
        _state(perimeter, "after auto_trimline", lines)

        points = perimeter.data.splines[0].bezier_points
        bvh = BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())
        outcome = _smooth_trim_controls_local(
            perimeter,
            scan,
            bvh,
            _TrimBrushConfig(
                center_index=8,
                radius_m=0.090,
                strength=0.60,
                visible_indices=frozenset(range(len(points))),
                lock_opening=False,
            ),
        )
        lines.append(
            f"brush: affected={outcome.affected} "
            f"max_move={outcome.maximum_movement_mm:.3f}mm"
        )
        _state(perimeter, "after brush", lines)

        settings.trim_fillet_radius = 0.30
        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result, error = {"CANCELLED"}, str(exc).strip()
        corset = bpy.data.objects.get("Rigo Corset")
        lines.append(f"generate={result}")
        lines.append(f"  error={error!r}")
        lines.append(f"  corset={'present' if corset else 'MISSING'}")
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
