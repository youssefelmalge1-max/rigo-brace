"""Is the build fragility specific to STRAIGHTEN, or does any arc edit trigger it?

straightenguarddbg found two different failures:
  (20,28) moved 105.15mm -> "0 open and 2 non-manifold edge(s)"
  (18,20) moved   0.37mm -> "5 local rim overlap(s)"
A 0.37mm edit breaking a build that succeeds unedited is not a Straighten
defect; it points at the rim/offset stage's known narrow stability margin
(trimline_ops:45-52). This runs the SAME arcs through SMOOTH_ARC as a control,
so the two causes can be separated before anything is blamed or disabled.
"""

import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

OUT = r"C:\Projects\Blender Add-on Braces\arcmodedbg_result.txt"
ARCS = [(17, 21), (18, 20), (20, 28), (24, 30), (10, 14), (30, 36), (2, 8)]
TRIES = {"n": 0}
LINES = []


def _controls(curve):
    return [
        curve.matrix_world @ p.co.copy()
        for p in curve.data.splines[0].bezier_points
    ]


def _trial(mode, arc):
    bpy.ops.rigo.auto_trimline()
    curve = bpy.data.objects["Rigo Trim Perimeter"]
    before = _controls(curve)
    for index, point in enumerate(curve.data.splines[0].bezier_points):
        point.select_control_point = arc[0] <= index <= arc[1]
    bpy.ops.rigo.smooth_trimline("INVOKE_DEFAULT", mode=mode)
    after = _controls(curve)
    moved = max((a - b).length * 1000.0 for a, b in zip(after, before))
    try:
        result = bpy.ops.rigo.generate_curve_corset()
        build = "OK" if result == {"FINISHED"} else "CANCELLED"
    except RuntimeError as exc:
        text = str(exc).strip().splitlines()[0]
        if "non-manifold" in text:
            build = "FAIL non-manifold"
        elif "overlap" in text:
            build = "FAIL rim overlap"
        else:
            build = "FAIL " + text[:40]
    return moved, build


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 40:
        return 0.1
    try:
        prepare_reference_design()
        # baseline: unedited template must build
        bpy.ops.rigo.auto_trimline()
        try:
            base = bpy.ops.rigo.generate_curve_corset()
            LINES.append(f"unedited template builds: {base}")
        except RuntimeError as exc:
            LINES.append(f"unedited template FAILS: {str(exc)[:80]}")
        LINES.append("")
        LINES.append(f"{'arc':>10} | {'SMOOTH_ARC':>28} | {'STRAIGHTEN':>28}")
        LINES.append("-" * 74)
        for arc in ARCS:
            row = []
            for mode in ("SMOOTH_ARC", "STRAIGHTEN"):
                moved, build = _trial(mode, arc)
                row.append(f"{moved:7.2f}mm {build:<18}")
            LINES.append(f"{str(arc):>10} | {row[0]:>28} | {row[1]:>28}")
    except Exception as error:  # noqa: BLE001
        LINES.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(LINES))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
