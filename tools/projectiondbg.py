"""Measure whether the cylindrical (theta, z) projection is injective on the
REAL patient scans, not on a synthetic torso.

The containment test both generators use assumes every horizontal slice of the
body is star-shaped about the vertical axis: one radial ray from outside must
meet the surface exactly once. Where a ray meets two or more sheets (arm,
axilla fold, scapula, breast shelf) BOTH sheets satisfy "inside the perimeter"
and both are retained into the shell.

Reports, per scan, the fraction of (theta, z) samples inside the brace's own
z-band whose inward ray crosses the surface more than once, and where.
"""

import math
import sys
import traceback

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_design, A_SCAN, B_SCAN  # noqa: E402

OUT = r"C:\Projects\Blender Add-on Braces\projectiondbg_result.txt"
TRIES = {"count": 0}
THETA_STEPS = 180
Z_STEPS = 60
EPSILON = 0.0008


def _write(lines):
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def _sheet_count(bvh, inverse, origin_world, direction_world, reach):
    """How many times an inward radial ray crosses the surface."""
    local_origin = inverse @ origin_world
    local_far = inverse @ (origin_world + direction_world * reach)
    direction = (local_far - local_origin).normalized()
    travelled = 0.0
    hits = 0
    while travelled < reach:
        hit = bvh.ray_cast(
            local_origin + direction * travelled, direction, reach - travelled
        )
        if hit[0] is None:
            break
        hits += 1
        travelled += max(hit[3], 0.0) + EPSILON
        if hits > 24:
            break
    return hits


def _measure(scan, settings, label, lines):
    perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
    axis = perimeter["rigo_trim_axis"]
    front = perimeter["rigo_trim_front"]
    axis_x, axis_y = float(axis[0]), float(axis[1])
    front_x, front_y = float(front[0]), float(front[1])

    corners = [scan.matrix_world @ Vector(c) for c in scan.bound_box]
    reach = 2.5 * max(
        max(c.x for c in corners) - min(c.x for c in corners),
        max(c.y for c in corners) - min(c.y for c in corners),
    )
    # Restrict to the z-band the trimline actually spans - that is the only
    # region the containment test is ever asked about.
    curve_z = [
        (perimeter.matrix_world @ point.co).z
        for point in perimeter.data.splines[0].bezier_points
    ]
    z_low, z_high = min(curve_z), max(curve_z)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    bvh = BVHTree.FromObject(scan, depsgraph)
    inverse = scan.matrix_world.inverted()

    total = multi = 0
    worst = 0
    multi_by_z = {}
    for zi in range(Z_STEPS):
        z = z_low + (z_high - z_low) * (zi + 0.5) / Z_STEPS
        row_multi = 0
        for ti in range(THETA_STEPS):
            angle = -math.pi + (ti + 0.5) * math.tau / THETA_STEPS
            radial = Vector(
                (
                    front_x * math.cos(angle) - front_y * math.sin(angle),
                    front_x * math.sin(angle) + front_y * math.cos(angle),
                    0.0,
                )
            )
            origin = Vector((axis_x, axis_y, z)) + radial * reach
            count = _sheet_count(bvh, inverse, origin, -radial, reach)
            total += 1
            if count > 1:
                multi += 1
                row_multi += 1
            worst = max(worst, count)
        if row_multi:
            multi_by_z[round((z - z_low) / (z_high - z_low), 2)] = row_multi

    fraction = multi / max(1, total)
    lines.append(
        f"{label}: rays={total} multi_sheet={multi} "
        f"fraction={fraction * 100.0:.2f}% worst_crossings={worst} "
        f"z_band=({z_low:.4f},{z_high:.4f})"
    )
    hot = sorted(multi_by_z.items(), key=lambda kv: -kv[1])[:6]
    lines.append(
        f"  worst normalised heights (0=bottom of trim, 1=top): "
        + ", ".join(f"{h:.2f}->{n}/{THETA_STEPS}" for h, n in hot)
    )
    return fraction


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.ops.rigo, "auto_trimline") and TRIES["count"] < 30:
        return 0.1
    lines = []
    try:
        scan, settings = prepare_design(A_SCAN, "RIGO_CHENEAU", opening_width=25.0)
        a_fraction = _measure(scan, settings, "A type model (RIGO_CHENEAU)", lines)

        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        scan_b, settings_b = prepare_design(B_SCAN, "B")
        b_fraction = _measure(scan_b, settings_b, "B type model (B)", lines)

        lines.append("")
        lines.append(
            "VERDICT: projection is "
            + (
                "NON-INJECTIVE on real scans"
                if max(a_fraction, b_fraction) > 0.001
                else "injective on these scans"
            )
        )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    _write(lines)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
