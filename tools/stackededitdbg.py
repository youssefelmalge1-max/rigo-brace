"""Does STACKING trimline edits make the brace unbuildable?

Found while gating the one-visible-line contract: Smooth All -> Smooth Arc ->
Straighten Arc, then Generate, fails with "Trim rim cannot be built safely
(0 open and 1 non-manifold edge(s))", while each edit generates fine on its
own (trimsmoothtest phase 1 straightens and builds green).

This isolates which combination is responsible, one edit added at a time,
rebuilding from a clean template trimline for each trial.
"""

import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

OUT = r"C:\Projects\Blender Add-on Braces\stackededitdbg_result.txt"
TRIES = {"n": 0}
LINES = []


def _select_arc(first, last):
    curve = bpy.data.objects["Rigo Trim Perimeter"]
    for index, point in enumerate(curve.data.splines[0].bezier_points):
        point.select_control_point = first <= index <= last


def _edit(mode):
    if mode != "SMOOTH":
        _select_arc(20, 28)
    bpy.ops.rigo.smooth_trimline("INVOKE_DEFAULT", mode=mode)


def _trial(sequence):
    bpy.ops.rigo.auto_trimline()
    for mode in sequence:
        _edit(mode)
    curve = bpy.data.objects["Rigo Trim Perimeter"]
    controls = len(curve.data.splines[0].bezier_points)
    try:
        result = bpy.ops.rigo.generate_curve_corset()
        detail = ""
    except RuntimeError as exc:
        result, detail = "{'CANCELLED'}", str(exc).strip().splitlines()[0][:96]
    LINES.append(f"  {' -> '.join(sequence) or '(no edit)':<46} "
                 f"controls={controls} generate={result} {detail}")


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 40:
        return 0.1
    try:
        prepare_reference_design()
        LINES.append("Each trial starts from a freshly generated template trimline.")
        for sequence in (
            [],
            ["SMOOTH"],
            ["SMOOTH_ARC"],
            ["STRAIGHTEN"],
            ["SMOOTH", "SMOOTH_ARC"],
            ["SMOOTH", "STRAIGHTEN"],
            ["SMOOTH_ARC", "STRAIGHTEN"],
            ["SMOOTH", "SMOOTH_ARC", "STRAIGHTEN"],
            ["SMOOTH", "SMOOTH"],
            ["SMOOTH", "SMOOTH", "SMOOTH"],
        ):
            _trial(sequence)
    except Exception as error:  # noqa: BLE001
        LINES.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(LINES))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
