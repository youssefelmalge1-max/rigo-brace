"""Reproduce the UI button press exactly: INVOKE_DEFAULT, no arguments.

The gate test always passed explicit arc_start/arc_end and pre-selected
points. The panel buttons pass only `mode` and go through invoke(), which is
a different path - and the user reports the trimline disappearing on press.
This drives each button the way the panel does and records, after every press:
object existence, spline count, control count, visibility, active object and
whether the curve still evaluates to visible geometry.
"""

import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

OUT = r"C:\Projects\Blender Add-on Braces\trimuidbg_result.txt"
TRIES = {"n": 0}
LINES = []


def _state(tag):
    curve = bpy.data.objects.get("Rigo Trim Perimeter")
    if curve is None:
        LINES.append(f"  {tag:<34} OBJECT MISSING")
        return
    splines = len(curve.data.splines)
    points = len(curve.data.splines[0].bezier_points) if splines else 0
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = curve.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        verts = len(mesh.vertices)
        evaluated.to_mesh_clear()
    except Exception:
        verts = -1
    active = getattr(bpy.context.view_layer.objects, "active", None)
    LINES.append(
        f"  {tag:<34} splines={splines} controls={points} "
        f"hidden={curve.hide_get()} evalverts={verts} "
        f"active={active.name if active else None!r}"
    )


def _press(mode):
    """Exactly what the panel button does: set mode, INVOKE_DEFAULT."""
    try:
        result = bpy.ops.rigo.smooth_trimline("INVOKE_DEFAULT", mode=mode)
        return f"{result}"
    except RuntimeError as exc:
        return f"RuntimeError: {str(exc).strip()[:100]}"


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    try:
        prepare_reference_design()
        _state("after Generate Template")

        # --- the user's flow: object mode, nothing selected, press Smooth All
        LINES.append("PRESS 'Smooth All' (no selection, object mode):")
        LINES.append(f"    -> {_press('SMOOTH')}")
        _state("after Smooth All")

        LINES.append("PRESS 'Smooth All' a second time:")
        LINES.append(f"    -> {_press('SMOOTH')}")
        _state("after Smooth All x2")

        # --- press an arc mode with NO selection (the likely user action)
        LINES.append("PRESS 'Smooth Arc' with NO selection:")
        LINES.append(f"    -> {_press('SMOOTH_ARC')}")
        _state("after Smooth Arc (no selection)")

        LINES.append("PRESS 'Straighten Arc' with NO selection:")
        LINES.append(f"    -> {_press('STRAIGHTEN')}")
        _state("after Straighten (no selection)")

        # --- now with a selection made in OBJECT mode
        curve = bpy.data.objects.get("Rigo Trim Perimeter")
        if curve is not None and curve.data.splines:
            for i, p in enumerate(curve.data.splines[0].bezier_points):
                p.select_control_point = 26 <= i <= 30
            LINES.append("PRESS 'Smooth Arc' WITH selection 26..30:")
            LINES.append(f"    -> {_press('SMOOTH_ARC')}")
            _state("after Smooth Arc (selected)")

        # --- and from EDIT mode, which is how a user really selects points
        curve = bpy.data.objects.get("Rigo Trim Perimeter")
        if curve is not None:
            bpy.ops.object.select_all(action="DESELECT")
            curve.select_set(True)
            bpy.context.view_layer.objects.active = curve
            bpy.ops.object.mode_set(mode="EDIT")
            LINES.append(f"  (entered EDIT mode: {bpy.context.mode})")
            LINES.append("PRESS 'Smooth All' FROM EDIT MODE:")
            LINES.append(f"    -> {_press('SMOOTH')}")
            _state("after Smooth All (from edit)")
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")

        # --- can the brace still build afterwards?
        try:
            gen = bpy.ops.rigo.generate_curve_corset()
            err = ""
        except RuntimeError as exc:
            gen, err = "{'CANCELLED'}", str(exc).strip()[:90]
        LINES.append(f"GENERATE after all presses: {gen} {err}")
    except Exception as error:  # noqa: BLE001
        LINES.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(LINES))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
