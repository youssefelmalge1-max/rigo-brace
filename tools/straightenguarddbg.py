"""Which precondition separates a straightenable arc from an unstraightenable one?

Known: arc 17..21 straightens and the brace BUILDS (trimsmoothtest phase 1);
arc 20..28 straightens and the brace FAILS. A guard must pass the first and
refuse the second, so both candidates are measured on several arcs, and each
arc is then actually built to get the ground truth.

Candidate A - chord penetration: how deep the straight chord between the
pinned endpoints goes inside the body. A chord across a convex torso is always
somewhat inside, so the question is how much.

Candidate B - view-facing span: the angle between the body normal and the view
direction along the arc. Past 90deg the arc has wrapped onto the far side of
the torso, where "lateral in the chosen view" stops being a tangential
direction at all and flattening pushes the path through the body.

Candidate C - post-condition: did the arc actually get straighter
(arc/chord ratio must not increase)?
"""

import math
import sys
import traceback

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

OUT = r"C:\Projects\Blender Add-on Braces\straightenguarddbg_result.txt"
ARCS = [(17, 21), (18, 20), (20, 28), (24, 30), (10, 14), (30, 36), (2, 8)]
TRIES = {"n": 0}
LINES = []


def _controls(curve):
    return [
        curve.matrix_world @ p.co.copy()
        for p in curve.data.splines[0].bezier_points
    ]


def _measure(curve, scan, bvh, arc):
    controls = _controls(curve)
    first, last = controls[arc[0]], controls[arc[1]]
    chord = last - first
    inverse = scan.matrix_world.inverted()
    rotation = scan.matrix_world.to_3x3()
    fx, fy = curve.get("rigo_trim_front", (0.0, -1.0))
    view = Vector((fx, fy, 0.0)).normalized()

    # A: chord penetration
    depths = []
    for step in range(21):
        point = first + chord * (step / 20.0)
        location, normal, _i, _d = bvh.find_nearest(inverse @ point)
        if location is None:
            continue
        depths.append(
            (point - (scan.matrix_world @ location)).dot(
                (rotation @ normal).normalized()
            ) * 1000.0
        )
    penetration = -min(depths) if depths else 0.0

    # B: view-facing span along the arc
    angles = []
    for index in range(arc[0], arc[1] + 1):
        point = controls[index]
        location, normal, _i, _d = bvh.find_nearest(inverse @ point)
        if location is None:
            continue
        world_normal = (rotation @ normal).normalized()
        # view points INTO the screen; the outward normal of a front-facing
        # sample opposes it
        angles.append(math.degrees(world_normal.angle(-view)))
    return {
        "chord_mm": chord.length * 1000.0,
        "penetration_mm": penetration,
        "normal_vs_view_max_deg": max(angles) if angles else 0.0,
    }


def _arc_chord_ratio(controls, arc):
    run = list(range(arc[0], arc[1] + 1))
    arclen = sum(
        (controls[run[i + 1]] - controls[run[i]]).length
        for i in range(len(run) - 1)
    )
    chord = (controls[run[-1]] - controls[run[0]]).length
    return arclen / chord if chord > 1e-12 else math.inf


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 40:
        return 0.1
    try:
        prepare_reference_design()
        LINES.append(
            f"{'arc':>10} {'chord_mm':>9} {'penetr_mm':>10} "
            f"{'norm_v_view':>12} {'ratio_before':>13} {'ratio_after':>12} "
            f"{'max_move_mm':>12}  build"
        )
        for arc in ARCS:
            bpy.ops.rigo.auto_trimline()
            curve = bpy.data.objects["Rigo Trim Perimeter"]
            scan = bpy.context.scene.rigo_brace.scan_object
            bvh = BVHTree.FromObject(
                scan, bpy.context.evaluated_depsgraph_get()
            )
            stats = _measure(curve, scan, bvh, arc)
            before = _controls(curve)
            ratio_before = _arc_chord_ratio(before, arc)
            for index, point in enumerate(curve.data.splines[0].bezier_points):
                point.select_control_point = arc[0] <= index <= arc[1]
            bpy.ops.rigo.smooth_trimline("INVOKE_DEFAULT", mode="STRAIGHTEN")
            after = _controls(curve)
            ratio_after = _arc_chord_ratio(after, arc)
            moved = max((a - b).length * 1000.0 for a, b in zip(after, before))
            try:
                result = bpy.ops.rigo.generate_curve_corset()
                build = "OK" if result == {"FINISHED"} else "CANCELLED"
            except RuntimeError as exc:
                build = "FAIL: " + str(exc).strip().splitlines()[0][:48]
            LINES.append(
                f"{str(arc):>10} {stats['chord_mm']:9.1f} "
                f"{stats['penetration_mm']:10.1f} "
                f"{stats['normal_vs_view_max_deg']:12.1f} "
                f"{ratio_before:13.4f} {ratio_after:12.4f} {moved:12.2f}  {build}"
            )
    except Exception as error:  # noqa: BLE001
        LINES.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(LINES))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
