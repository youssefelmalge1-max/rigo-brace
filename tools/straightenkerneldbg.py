"""WHICH controls does Straighten move 105mm, and where do they land?

Stage 2 of straightendbg showed one control displaced 105.151mm and the arc
getting LESS straight (chord ratio 1.984 -> 2.178). Hypothesis: the kernel
flattens the arc onto the CHORD between its endpoints, and for an arc that
wraps the torso that chord passes THROUGH the body, so the samples are pulled
inside and the depth re-imposition then re-projects them onto whatever surface
is nearest - possibly the far side.

Measured: per-control displacement, signed distance to the body before and
after, the chord's own relationship to the body, and the arc's angular span.
"""

import math
import sys
import traceback

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import trimsmooth_ops  # noqa: E402

OUT = r"C:\Projects\Blender Add-on Braces\straightenkerneldbg_result.txt"
ARC = (20, 28)
TRIES = {"n": 0}
LINES = []


def _controls(curve):
    return [
        curve.matrix_world @ p.co.copy()
        for p in curve.data.splines[0].bezier_points
    ]


def _signed_mm(scan, bvh, points):
    inverse = scan.matrix_world.inverted()
    rotation = scan.matrix_world.to_3x3()
    out = []
    for point in points:
        location, normal, _i, _d = bvh.find_nearest(inverse @ point)
        if location is None:
            out.append(None)
            continue
        out.append(
            (point - (scan.matrix_world @ location)).dot(
                (rotation @ normal).normalized()
            ) * 1000.0
        )
    return out


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 40:
        return 0.1
    try:
        prepare_reference_design()
        curve = bpy.data.objects["Rigo Trim Perimeter"]
        scan = bpy.context.scene.rigo_brace.scan_object
        bvh = BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())

        before = _controls(curve)
        before_mm = _signed_mm(scan, bvh, before)

        # the arc as the kernel sees it
        first, last = before[ARC[0]], before[ARC[1]]
        chord = last - first
        fx, fy = curve.get("rigo_trim_front", (0.0, -1.0))
        view = Vector((fx, fy, 0.0)).normalized()
        LINES.append(f"view direction (rigo_trim_front) = "
                     f"({view.x:.3f},{view.y:.3f},{view.z:.3f})")
        LINES.append(f"arc {ARC}: chord length={chord.length*1000:.1f}mm")

        # does the CHORD itself pass through the body?
        LINES.append("")
        LINES.append("chord sampled every 10%: signed distance to body (mm)")
        chord_points = [first + chord * (step / 10.0) for step in range(11)]
        chord_mm = _signed_mm(scan, bvh, chord_points)
        LINES.append("   " + "  ".join(
            f"{step*10}%:{value:+.1f}" for step, value in enumerate(chord_mm)
        ))
        inside = sum(1 for v in chord_mm if v is not None and v < 0.0)
        LINES.append(f"   chord samples INSIDE the body: {inside}/{len(chord_mm)}")

        # angular span of the arc about the trunk axis
        ax, ay = curve.get("rigo_trim_axis", (0.0, 0.0))
        centre = Vector((ax, ay, 0.0))
        angles = []
        for index in range(ARC[0], ARC[1] + 1):
            point = before[index]
            angles.append(math.atan2(point.y - centre.y, point.x - centre.x))
        span = max(angles) - min(angles)
        LINES.append(f"arc angular span about the trunk axis = "
                     f"{math.degrees(span):.1f} deg")

        for index, point in enumerate(curve.data.splines[0].bezier_points):
            point.select_control_point = ARC[0] <= index <= ARC[1]
        bpy.ops.rigo.smooth_trimline("INVOKE_DEFAULT", mode="STRAIGHTEN")

        after = _controls(curve)
        after_mm = _signed_mm(scan, bvh, after)
        LINES.append("")
        LINES.append("per-control displacement and body adherence:")
        LINES.append("  idx   moved_mm   before_mm   after_mm   in_arc")
        for index in range(len(before)):
            moved = (after[index] - before[index]).length * 1000.0
            if moved < 0.001 and not (ARC[0] <= index <= ARC[1]):
                continue
            LINES.append(
                f"  {index:3d}  {moved:9.3f}  {before_mm[index]:+9.3f}  "
                f"{after_mm[index]:+9.3f}   {'YES' if ARC[0] <= index <= ARC[1] else ''}"
            )
        moved_all = [(a - b).length * 1000.0 for a, b in zip(after, before)]
        worst = max(range(len(moved_all)), key=lambda i: moved_all[i])
        LINES.append("")
        LINES.append(f"WORST control {worst}: moved {moved_all[worst]:.3f}mm, "
                     f"{before[worst].x:.3f},{before[worst].y:.3f},{before[worst].z:.3f}"
                     f"  ->  {after[worst].x:.3f},{after[worst].y:.3f},{after[worst].z:.3f}")
        LINES.append(f"  is control {worst} inside the selected arc "
                     f"{ARC}? {ARC[0] <= worst <= ARC[1]}")
        outside_moved = [
            (i, moved_all[i]) for i in range(len(moved_all))
            if not (ARC[0] <= i <= ARC[1]) and moved_all[i] > 0.001
        ]
        LINES.append(f"  controls OUTSIDE the arc that moved: {outside_moved[:12]}")
    except Exception as error:  # noqa: BLE001
        LINES.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(LINES))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
