"""P2 prototype v2: global C2 spline solve + sagitta-driven stations.

Prototype v1 measured a decisive negative: per-side Bessel/third-of-chord
tangents left the junction-curvature ratio at 9.91 (from 9.70). That is not a
tuning miss - ANY locally derived tangent rule gives C1 at best, because the
curvature entering a control point is fixed by the segment on its left and the
curvature leaving it by the segment on its right, and no local rule couples
them. Curvature continuity needs the global solve.

This prototype therefore tests:

  1  periodic C2 cubic-spline tangents (the standard non-uniform tridiagonal
     system, solved by Gauss-Seidel - the matrix is strictly diagonally
     dominant with ratio 2, so it converges geometrically), expressed exactly
     in the existing Bezier representation as handles at d_i * h_i / 3
  2  sagitta-driven station insertion: subdivide the segment whose evaluated
     midpoint sits furthest off the body, repeat until every segment is within
     tolerance - this bounds the displayed-versus-built gap directly instead
     of hoping a chord-length cap implies it
  3  optional handle-reach clamp, to see whether C2 overshoots at the opening

Measures the honest displayed-versus-built pair: total distance, and the
TANGENTIAL component with the intended liner-offset normal component removed.

Writes trimp2proto2_result.txt; quits Blender itself.
"""

import math
import os
import sys
import traceback

import bpy
from mathutils import Vector
from mathutils.geometry import interpolate_bezier
from mathutils.kdtree import KDTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    design_ops,
    trimline_ops,
)

OUT = r"C:\Projects\Blender Add-on Braces\trimp2proto2_result.txt"
TRIES = {"n": 0}
CAP = {}

SAGITTA_TOL_M = float(os.environ.get("RIGO_P2_SAGITTA", "0.0006"))
CONTROL_CAP = int(os.environ.get("RIGO_P2_CONTROLS", "120"))
REACH_CLAMP = float(os.environ.get("RIGO_P2_REACH_CLAMP", "0.0"))

_orig_projected = curve_build_ops._projected_samples


def _projected_spy(base, perimeter):
    coordinates, normals = _orig_projected(base, perimeter)
    if "projected" not in CAP:
        matrix = base.matrix_world
        CAP["projected"] = [matrix @ c for c in coordinates]
        CAP["projected_normals"] = [
            (matrix.inverted().transposed().to_3x3() @ n).normalized()
            for n in normals
        ]
    return coordinates, normals


def _pct(values, fraction):
    if not values:
        return 0.0
    return values[int(fraction * (len(values) - 1))]


def _curvature(a, b, c):
    first, second, third = (b - a).length, (c - b).length, (c - a).length
    if min(first, second, third) <= 1e-12:
        return 0.0
    half = (first + second + third) * 0.5
    area_sq = max(half * (half - first) * (half - second) * (half - third), 0.0)
    if area_sq <= 1e-24:
        return 0.0
    return (4.0 * math.sqrt(area_sq)) / (first * second * third)


def _junction_ratio(spline):
    points = spline.bezier_points
    count = len(points)
    segments = [
        interpolate_bezier(
            points[i].co,
            points[i].handle_right,
            points[(i + 1) % count].handle_left,
            points[(i + 1) % count].co,
            65,
        )
        for i in range(count)
    ]
    jumps, within = [], []
    for i in range(count):
        previous, current = segments[i - 1], segments[i]
        jumps.append(
            abs(
                _curvature(current[0], current[1], current[2])
                - _curvature(previous[62], previous[63], previous[64])
            )
        )
        for s in range(1, 63):
            within.append(
                abs(
                    _curvature(current[s], current[s + 1], current[s + 2])
                    - _curvature(current[s - 1], current[s], current[s + 1])
                )
            )
    jumps.sort()
    within.sort()
    baseline = max(_pct(within, 0.95), 1.0e-9)
    return _pct(jumps, 0.95) / baseline, _pct(jumps, 0.95), baseline


def _periodic_c2_tangents(coordinates, passes=200):
    """Solve the closed non-uniform C2 cubic-spline tangent system."""
    count = len(coordinates)
    spans = [
        max((coordinates[(i + 1) % count] - coordinates[i]).length, 1.0e-9)
        for i in range(count)
    ]
    right_hand = []
    for i in range(count):
        h_prev, h_next = spans[i - 1], spans[i]
        right_hand.append(
            (
                (coordinates[i] - coordinates[i - 1]) * (h_next / h_prev)
                + (coordinates[(i + 1) % count] - coordinates[i])
                * (h_prev / h_next)
            )
            * 3.0
        )
    tangents = [
        (coordinates[(i + 1) % count] - coordinates[i - 1]).normalized()
        for i in range(count)
    ]
    for _pass in range(passes):
        for i in range(count):
            h_prev, h_next = spans[i - 1], spans[i]
            tangents[i] = (
                right_hand[i]
                - tangents[i - 1] * h_next
                - tangents[(i + 1) % count] * h_prev
            ) / (2.0 * (h_prev + h_next))
    return tangents, spans


def _apply_c2_handles(spline, reach_clamp=0.0):
    points = spline.bezier_points
    coordinates = [point.co.copy() for point in points]
    tangents, spans = _periodic_c2_tangents(coordinates)
    count = len(points)
    for i, point in enumerate(points):
        h_prev, h_next = spans[i - 1], spans[i]
        right = tangents[i] * (h_next / 3.0)
        left = tangents[i] * (h_prev / 3.0)
        if reach_clamp > 0.0:
            if right.length > reach_clamp * h_next:
                right = right.normalized() * (reach_clamp * h_next)
            if left.length > reach_clamp * h_prev:
                left = left.normalized() * (reach_clamp * h_prev)
        point.handle_left_type = "FREE"
        point.handle_right_type = "FREE"
        point.handle_right = coordinates[i] + right
        point.handle_left = coordinates[i] - left


def _segment_midpoint(points, index):
    count = len(points)
    second = points[(index + 1) % count]
    p0, p1 = points[index].co, points[index].handle_right
    p2, p3 = second.handle_left, second.co
    q0, q1, q2 = (p0 + p1) * 0.5, (p1 + p2) * 0.5, (p2 + p3) * 0.5
    r0, r1 = (q0 + q1) * 0.5, (q1 + q2) * 0.5
    return (r0 + r1) * 0.5


def _off_surface_m(curve, scan, bvh, local_point):
    world = curve.matrix_world @ local_point
    fitted = trimline_ops._nearest_surface_world(scan, bvh, world)
    if fitted is None:
        return 0.0
    return (world - fitted).length


def _subdivide_after(curve, index):
    spline = curve.data.splines[0]
    points = spline.bezier_points
    count = len(points)
    states = []
    for i, point in enumerate(points):
        states.append(
            (point.co.copy(), point.handle_left.copy(), point.handle_right.copy())
        )
        if i != index:
            continue
        second = points[(i + 1) % count]
        p0, p1 = point.co, point.handle_right
        p2, p3 = second.handle_left, second.co
        q0, q1, q2 = (p0 + p1) * 0.5, (p1 + p2) * 0.5, (p2 + p3) * 0.5
        r0, r1 = (q0 + q1) * 0.5, (q1 + q2) * 0.5
        states.append(((r0 + r1) * 0.5, r0, r1))
    curve.data.splines.remove(spline)
    new_spline = curve.data.splines.new("BEZIER")
    new_spline.use_cyclic_u = True
    new_spline.bezier_points.add(len(states) - 1)
    for point, (co, left, right) in zip(new_spline.bezier_points, states):
        point.co = co
        point.handle_left_type = "FREE"
        point.handle_right_type = "FREE"
        point.handle_left = left
        point.handle_right = right
    curve.data.update_tag()
    return index + 1


def _refine_to_surface(context, curve, scan, bvh, lines):
    """Insert stations where the curve bulges off the body, re-solving C2."""
    fit = trimline_ops._radial_fit_context(context, curve, scan)
    inserted = 0
    for _step in range(CONTROL_CAP):
        spline = curve.data.splines[0]
        points = spline.bezier_points
        if len(points) >= CONTROL_CAP:
            break
        worst_index, worst_value = -1, 0.0
        for index in range(len(points)):
            deviation = _off_surface_m(
                curve, scan, bvh, _segment_midpoint(points, index)
            )
            if deviation > worst_value:
                worst_index, worst_value = index, deviation
        if worst_index < 0 or worst_value <= SAGITTA_TOL_M:
            break
        new_index = _subdivide_after(curve, worst_index)
        point = curve.data.splines[0].bezier_points[new_index]
        fitted = trimline_ops._radial_surface_world(
            fit, curve.matrix_world @ point.co
        )
        if fitted is not None:
            delta = curve.matrix_world.inverted() @ fitted - point.co
            point.co += delta
            point.handle_left += delta
            point.handle_right += delta
        _apply_c2_handles(curve.data.splines[0], REACH_CLAMP)
        inserted += 1
    lines.append(
        f"  sagitta refinement: +{inserted} stations "
        f"(tol {SAGITTA_TOL_M*1000:.2f}mm, cap {CONTROL_CAP})"
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


def _display_vs_raw(perimeter):
    dense = curve_build_ops._curve_world_samples(perimeter)
    displayed = _centerline(perimeter)
    tree = KDTree(len(dense))
    for index, point in enumerate(dense):
        tree.insert(point, index)
    tree.balance()
    gaps = sorted(tree.find(point)[2] for point in displayed)
    return _pct(gaps, 0.95) * 1000.0, gaps[-1] * 1000.0


def _display_vs_built(perimeter):
    """Displayed line against the true cutter path: total and tangential."""
    built = CAP.get("projected")
    normals = CAP.get("projected_normals")
    if not built:
        return None
    displayed = _centerline(perimeter)
    tree = KDTree(len(built))
    for index, point in enumerate(built):
        tree.insert(point, index)
    tree.balance()
    total, tangential = [], []
    for point in displayed:
        location, index, distance = tree.find(point)
        total.append(distance)
        delta = point - location
        normal = normals[index]
        tangential.append((delta - normal * delta.dot(normal)).length)
    total.sort()
    tangential.sort()
    return (
        _pct(total, 0.95) * 1000.0,
        total[-1] * 1000.0,
        _pct(tangential, 0.95) * 1000.0,
        tangential[-1] * 1000.0,
    )


def _min_non_adjacent_gap(points):
    count = len(points)
    skip = max(4, count // 20)
    best = math.inf
    step = max(1, count // 600)
    for i in range(0, count, step):
        for j in range(0, count, step):
            if min((j - i) % count, (i - j) % count) < skip:
                continue
            best = min(best, (points[i] - points[j]).length)
    return best


def _spacing(spline):
    points = spline.bezier_points
    count = len(points)
    values = sorted(
        (points[(i + 1) % count].co - points[i].co).length for i in range(count)
    )
    return values[0] * 1000.0, values[-1] * 1000.0, values[-1] / max(values[0], 1e-9)


def _corner_indices(perimeter):
    half = float(perimeter.get("rigo_trim_opening_deg", 10.0)) / 2.0
    axis = tuple(perimeter.get("rigo_trim_axis", (0.0, 0.0)))
    front = tuple(perimeter.get("rigo_trim_front", (0.0, -1.0)))
    matrix = perimeter.matrix_world
    points = perimeter.data.splines[0].bezier_points
    thetas = [
        math.degrees(trimline_ops._curve_angle(matrix @ p.co, axis, front))
        for p in points
    ]
    return sorted(range(len(points)), key=lambda i: abs(abs(thetas[i]) - half))[:4]


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = [
        f"sagitta_tol_mm={SAGITTA_TOL_M*1000:.2f} control_cap={CONTROL_CAP} "
        f"reach_clamp={REACH_CLAMP}"
    ]
    try:
        curve_build_ops._projected_samples = _projected_spy
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        perimeter = bpy.data.objects["Rigo Trim Perimeter"]
        from mathutils.bvhtree import BVHTree

        bvh = BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())

        ratio, jump, base = _junction_ratio(perimeter.data.splines[0])
        p95, worst = _display_vs_raw(perimeter)
        spacing = _spacing(perimeter.data.splines[0])
        lines.append(
            f"BEFORE: controls={len(perimeter.data.splines[0].bezier_points)} "
            f"spacing {spacing[0]:.1f}-{spacing[1]:.1f}mm ({spacing[2]:.1f}x) "
            f"junction_ratio={ratio:.2f} (jump {jump:.1f} / base {base:.2f}) "
            f"display-vs-raw p95={p95:.3f} max={worst:.3f}mm"
        )
        corners = _corner_indices(perimeter)
        corner_before = [
            perimeter.data.splines[0].bezier_points[i].co.copy() for i in corners
        ]

        # Step 1: C2 solve alone, on the original 42 stations.
        _apply_c2_handles(perimeter.data.splines[0], REACH_CLAMP)
        perimeter.data.update_tag()
        bpy.context.view_layer.update()
        ratio, jump, base = _junction_ratio(perimeter.data.splines[0])
        p95, worst = _display_vs_raw(perimeter)
        lines.append(
            f"C2 ONLY: junction_ratio={ratio:.2f} (jump {jump:.1f} / "
            f"base {base:.2f}) display-vs-raw p95={p95:.3f} max={worst:.3f}mm"
        )

        # Step 2: sagitta-driven stations, re-solving C2 after each insertion.
        _refine_to_surface(bpy.context, perimeter, scan, bvh, lines)
        perimeter.data.update_tag()
        bpy.context.view_layer.update()
        ratio, jump, base = _junction_ratio(perimeter.data.splines[0])
        p95, worst = _display_vs_raw(perimeter)
        spacing = _spacing(perimeter.data.splines[0])
        lines.append(
            f"AFTER:  controls={len(perimeter.data.splines[0].bezier_points)} "
            f"spacing {spacing[0]:.1f}-{spacing[1]:.1f}mm ({spacing[2]:.1f}x) "
            f"junction_ratio={ratio:.2f} (jump {jump:.1f} / base {base:.2f}) "
            f"display-vs-raw p95={p95:.3f} max={worst:.3f}mm"
        )
        moves = [
            (perimeter.data.splines[0].bezier_points[i].co - before).length * 1000.0
            for i, before in zip(_corner_indices(perimeter), corner_before)
        ]
        lines.append(f"  corner stations moved: max {max(moves):.4f}mm")
        dense = curve_build_ops._curve_world_samples(perimeter)
        self_gap = _min_non_adjacent_gap(dense) * 1000.0
        lines.append(f"  min non-adjacent self-gap={self_gap:.2f}mm")
        turns = sorted(
            math.degrees(
                (dense[i] - dense[i - 1]).angle(dense[(i + 1) % len(dense)] - dense[i])
            )
            for i in range(len(dense))
            if (dense[i] - dense[i - 1]).length > 1e-9
            and (dense[(i + 1) % len(dense)] - dense[i]).length > 1e-9
        )
        lines.append(
            f"  dense turn_deg p50={_pct(turns, 0.5):.3f} "
            f"p95={_pct(turns, 0.95):.3f} max={turns[-1]:.2f}"
        )

        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result, error = {"CANCELLED"}, str(exc).strip()[:160]
        lines.append(f"generate={result} {error}")
        corset = bpy.data.objects.get("Rigo Corset")
        if corset is not None:
            lines.append(
                f"  corset: intersections="
                f"{corset.get('rigo_generation_rim_intersections')} "
                f"zero_area={corset.get('rigo_generation_zero_area_faces')} "
                f"trim p95={corset.get('rigo_trim_curve_p95_error_mm', -1):.4f} "
                f"max={corset.get('rigo_trim_curve_max_error_mm', -1):.4f}mm "
                f"fillet_mean="
                f"{corset.get('rigo_trim_fillet_mean_radius_mm', -1):.3f}mm"
            )
        built = _display_vs_built(perimeter)
        if built is not None:
            lines.append(
                f"  DISPLAY vs BUILT: total p95={built[0]:.3f} max={built[1]:.3f}mm | "
                f"tangential p95={built[2]:.3f} max={built[3]:.3f}mm"
            )
        ok = (
            ratio <= 3.0
            and max(moves) <= 0.5
            and self_gap > 3.0
            and result == {"FINISHED"}
            and built is not None
            and built[2] <= 1.0
            and built[3] <= 2.0
        )
        lines.append(f"PROTO_PASS={ok}")
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
        lines.append("PROTO_PASS=False")
    finally:
        curve_build_ops._projected_samples = _orig_projected
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
