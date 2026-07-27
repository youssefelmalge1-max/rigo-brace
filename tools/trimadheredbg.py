"""Which trimline path sinks into the mold, and by how much? Measurement only.

The orthotist sees the editable trimline disappear inside the body. Several
different curves are on screen at different moments, and they are NOT the same
geometry, so the first job is to say which one is sinking before anything is
changed:

  1 authoritative clinical Bezier   `Rigo Trim Perimeter`, raw control curve
  2 display preview                 the same object EVALUATED, i.e. after its
                                    Shrinkwrap modifier
  3 shrinkwrap target check         what that modifier is actually aimed at
  4 cutter/perimeter object         `Rigo Build Trim Perimeter`, built from
                                    the projected samples (BRACE view only)
  5 cut boundary                    where the shell was actually cut

Distances are SIGNED along the body's outward surface normal: negative means
inside the patient, which is the failure the orthotist is describing, and
positive means floating above the skin, which is only a display choice. An
unsigned distance cannot tell those apart, which is why every earlier report
in this project that used one had to be re-measured.

Reported per curve: signed p1/p5/p50/p95/p99, the worst inward excursion, how
much of the curve is inside the body at all, and where the worst point sits in
(theta, z) so it can be found in the viewport.

Writes trimadheredbg_result.txt; quits Blender itself.
"""

import math
import sys
import traceback

import bpy
from mathutils.bvhtree import BVHTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    design_ops,
    trimline_ops,
)

OUT = r"C:\Projects\Blender Add-on Braces\trimadheredbg_result.txt"
TRIES = {"n": 0}


def _pct(values, fraction):
    if not values:
        return 0.0
    return values[int(fraction * (len(values) - 1))]


def _signed_distances(points, target):
    """Signed distance to `target`; negative = inside the body."""
    bvh = BVHTree.FromObject(target, bpy.context.evaluated_depsgraph_get())
    inverse = target.matrix_world.inverted()
    normal_matrix = inverse.transposed().to_3x3()
    signed = []
    for point in points:
        local = inverse @ point
        hit = bvh.find_nearest(local)
        if hit[0] is None:
            continue
        surface = target.matrix_world @ hit[0]
        normal = (normal_matrix @ hit[1]).normalized()
        signed.append(((point - surface).dot(normal), point))
    return signed


def _theta_z(perimeter, point):
    axis = tuple(perimeter.get("rigo_trim_axis", (0.0, 0.0)))
    front = tuple(perimeter.get("rigo_trim_front", (0.0, -1.0)))
    return (
        math.degrees(trimline_ops._curve_angle(point, axis, front)),
        point.z * 1000.0,
    )


def _report(label, points, target, perimeter, lines):
    if not points:
        lines.append(f"{label}: (no points)")
        return
    signed = _signed_distances(points, target)
    if not signed:
        lines.append(f"{label}: (no surface hits)")
        return
    values = sorted(value for value, _point in signed)
    inside = [value for value in values if value < 0.0]
    worst_value, worst_point = min(signed, key=lambda entry: entry[0])
    theta, height = _theta_z(perimeter, worst_point)
    lines.append(
        f"{label}: n={len(values)} signed_mm "
        f"p1={_pct(values, 0.01)*1000:+.3f} p5={_pct(values, 0.05)*1000:+.3f} "
        f"p50={_pct(values, 0.50)*1000:+.3f} p95={_pct(values, 0.95)*1000:+.3f} "
        f"p99={_pct(values, 0.99)*1000:+.3f}"
    )
    lines.append(
        f"    worst inward={worst_value*1000:+.3f}mm at theta={theta:+.1f}deg "
        f"z={height:.0f}mm | inside the body: {len(inside)}/{len(values)} "
        f"({100.0*len(inside)/len(values):.1f}%) | "
        f"max outward={values[-1]*1000:+.3f}mm"
    )


def _centerline(obj):
    bevel = obj.data.bevel_depth
    obj.data.bevel_depth = 0.0
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    points = [obj.matrix_world @ vertex.co for vertex in mesh.vertices]
    evaluated.to_mesh_clear()
    obj.data.bevel_depth = bevel
    return points


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = []
    try:
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        perimeter = bpy.data.objects["Rigo Trim Perimeter"]

        lines.append("=== WHAT IS ON SCREEN ===")
        for obj in sorted(bpy.data.objects, key=lambda o: o.name):
            if obj.type != "CURVE":
                continue
            modifiers = [
                f"{m.type}->{getattr(m.target, 'name', '-')} "
                f"mode={getattr(m, 'wrap_mode', '-')} "
                f"offset={getattr(m, 'offset', 0.0)*1000:.2f}mm"
                for m in obj.modifiers
            ]
            lines.append(
                f"  {obj.name!r} {'HIDDEN' if obj.hide_get() else 'visible'} "
                f"bevel={obj.data.bevel_depth*1000:.2f}mm "
                f"controls={sum(len(s.bezier_points) for s in obj.data.splines)} "
                f"modifiers={modifiers}"
            )
        lines.append(
            f"  SURFACE_OFFSET constant = "
            f"{trimline_ops.SURFACE_OFFSET*1000:.2f}mm (intended standoff)"
        )
        lines.append("")
        lines.append("=== SIGNED DISTANCE TO THE PATIENT BODY (scan) ===")
        lines.append("negative = inside the patient; positive = above the skin")
        lines.append("")

        # 1 - the authoritative clinical curve, control points only.
        matrix = perimeter.matrix_world
        controls = [
            matrix @ point.co
            for point in perimeter.data.splines[0].bezier_points
        ]
        _report("1a CONTROL POINTS (authoritative)", controls, scan, perimeter, lines)

        # 1b - the authoritative curve as the CUTTER reads it (raw bezier).
        raw = curve_build_ops._curve_world_samples(perimeter)
        _report("1b RAW BEZIER (what Generate samples)", raw, scan, perimeter, lines)

        # 2 - what the orthotist actually sees in TRIM view.
        displayed = _centerline(perimeter)
        _report("2  DISPLAYED (after Shrinkwrap)", displayed, scan, perimeter, lines)

        lines.append("")
        lines.append("=== AFTER GENERATE ===")
        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result, error = {"CANCELLED"}, str(exc).strip()[:100]
        lines.append(f"generate={result} {error}")
        base = bpy.data.objects.get("Rigo Corset Base")
        overlay = bpy.data.objects.get("Rigo Build Trim Perimeter")
        corset = bpy.data.objects.get("Rigo Corset")

        if overlay is not None:
            _report(
                "4  CUTTER/OVERLAY vs body",
                _centerline(overlay),
                scan,
                perimeter,
                lines,
            )
            if base is not None:
                _report(
                    "4b CUTTER/OVERLAY vs offset mold",
                    _centerline(overlay),
                    base,
                    perimeter,
                    lines,
                )
        if base is not None:
            _report(
                "1c RAW BEZIER vs offset mold (the projection target)",
                raw,
                base,
                perimeter,
                lines,
            )
        if corset is not None:
            group = corset.vertex_groups.get(design_ops._RIM_BOUNDARY_GROUP)
            if group is not None:
                rim = [
                    corset.matrix_world @ vertex.co
                    for vertex in corset.data.vertices
                    if any(entry.group == group.index for entry in vertex.groups)
                ]
                _report("5  CUT RIM vs body", rim, scan, perimeter, lines)
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
