"""Who moves control 3 during an arc edit at 26..30? Stage bisect.

Snapshots control 3's co and handles at every internal stage of one
rigo.smooth_trimline SMOOTH_ARC call, by wrapping the module functions.
"""

import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    trimline_ops,
    trimsmooth_ops,
)

OUT = r"C:\Projects\Blender Add-on Braces\trimlocdbg_result.txt"
TRIES = {"n": 0}
LINES = []
BASE = {}


def _snap(tag):
    curve = bpy.data.objects.get("Rigo Trim Perimeter")
    if curve is None:
        return
    p = curve.data.splines[0].bezier_points[3]
    if "co" not in BASE:
        BASE["co"] = p.co.copy()
        BASE["hl"] = p.handle_left.copy()
        BASE["hr"] = p.handle_right.copy()
    LINES.append(
        f"  {tag:<28} d_co={(p.co-BASE['co']).length:.3e} "
        f"d_hl={(p.handle_left-BASE['hl']).length:.3e} "
        f"d_hr={(p.handle_right-BASE['hr']).length:.3e}"
    )


_orig_redepth = trimsmooth_ops._redepth
_orig_band = trimsmooth_ops.solve_band_c2
_orig_mark = trimsmooth_ops.mark_handles_solved
_orig_kernel = trimsmooth_ops._kernel_smooth


def _redepth_spy(*a, **k):
    _snap("before _redepth")
    r = _orig_redepth(*a, **k)
    _snap("after _redepth")
    return r


def _band_spy(*a, **k):
    _snap("before solve_band_c2")
    r = _orig_band(*a, **k)
    _snap("after solve_band_c2")
    return r


def _mark_spy(*a, **k):
    _snap("before mark_handles_solved")
    r = _orig_mark(*a, **k)
    _snap("after mark_handles_solved")
    return r


def _kernel_spy(*a, **k):
    _snap("before kernel")
    r = _orig_kernel(*a, **k)
    _snap("after kernel")
    return r


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    try:
        prepare_reference_design()
        _snap("after auto_trimline")
        trimsmooth_ops._redepth = _redepth_spy
        trimsmooth_ops.solve_band_c2 = _band_spy
        trimsmooth_ops.mark_handles_solved = _mark_spy
        trimsmooth_ops._kernel_smooth = _kernel_spy
        curve = bpy.data.objects["Rigo Trim Perimeter"]
        for i, pt in enumerate(curve.data.splines[0].bezier_points):
            on = i in (26, 30)
            pt.select_control_point = on
        _snap("after selection")
        bpy.ops.rigo.smooth_trimline(
            mode="SMOOTH_ARC", smoothness=12.0, preserve=0.2,
            influence=25.0, arc_start=26, arc_end=30,
            adaptive_refine=False,
        )
        _snap("after operator")
        LINES.append(f"stale={trimline_ops.handles_are_stale(curve)}")
    except Exception as error:  # noqa: BLE001
        LINES.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    finally:
        trimsmooth_ops._redepth = _orig_redepth
        trimsmooth_ops.solve_band_c2 = _orig_band
        trimsmooth_ops.mark_handles_solved = _orig_mark
        trimsmooth_ops._kernel_smooth = _orig_kernel
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(LINES))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
