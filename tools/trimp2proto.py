"""P2 prototype: station densification + per-side tangent reach, live-curve only.

Proves the two generator changes on the REAL curve object and the REAL build,
without modifying the installed add-on:

  1  subdivide every control interval whose chord exceeds the spacing cap,
     snapping only the new midpoints onto the body with the generator's own
     radial drape (`_radial_surface_world`) - existing stations, including the
     four opening corners, are byte-identical before/after
  2  re-derive all handles with chord-length Bessel tangents and per-side
     third-of-chord reach (the proposed replacement for 0.25 x min-chord)

Then measures the P2 gate set and runs the full Generate.
Writes trimp2proto_result.txt; quits Blender itself.
"""

import math
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
    trimline_ops,
)

OUT = r"C:\Projects\Blender Add-on Braces\trimp2proto_result.txt"
TRIES = {"n": 0}
SPACING_CAP_M = 0.040
CONTROL_CAP = 96
REACH_FRACTION = 1.0 / 3.0
REACH_LIMIT = 0.45


def _pct(sorted_values, fraction):
    if not sorted_values:
        return 0.0
    return sorted_values[int(fraction * (len(sorted_values) - 1))]


def _curvature(a, b, c):
    first, second, third = (b - a).length, (c - b).length, (c - a).length
    if min(first, second, third) <= 1e-12:
        return 0.0
    half = (first + second + third) * 0.5
    area_sq = max(half * (half - first) * (half - second) * (half - third), 0.0)
    if area_sq <= 1e-24:
        return 0.0
    return (4.0 * math.sqrt(area_sq)) / (first * second * third)


def _junction_ratio(perimeter):
    points = perimeter.data.splines[0].bezier_points
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
    return _pct(jumps, 0.95) / baseline


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


def _displayed_vs_built(perimeter):
    dense = curve_build_ops._curve_world_samples(perimeter)
    displayed = _centerline(perimeter)
    tree = KDTree(len(dense))
    for index, point in enumerate(dense):
        tree.insert(point, index)
    tree.balance()
    gaps = sorted(tree.find(point)[2] for point in displayed)
    return _pct(gaps, 0.95) * 1000.0, gaps[-1] * 1000.0


def _bessel_handles(spline):
    """Chord-length Bessel tangents with per-side third-of-chord reach."""
    points = spline.bezier_points
    count = len(points)
    coordinates = [point.co.copy() for point in points]
    for index in range(count):
        previous = coordinates[(index - 1) % count]
        current = coordinates[index]
        following = coordinates[(index + 1) % count]
        l_prev = (current - previous).length
        l_next = (following - current).length
        if min(l_prev, l_next) <= 1.0e-12:
            continue
        tangent = (following - current) * (
            l_prev * l_prev
        ) + (current - previous) * (l_next * l_next)
        if tangent.length <= 1.0e-12:
            continue
        tangent.normalize()
        point = points[index]
        point.handle_left_type = "FREE"
        point.handle_right_type = "FREE"
        point.handle_left = current - tangent * min(
            REACH_FRACTION * l_prev, REACH_LIMIT * l_prev
        )
        point.handle_right = current + tangent * min(
            REACH_FRACTION * l_next, REACH_LIMIT * l_next
        )


def _subdivided_states(points, split_after):
    """Point states with de-Casteljau midpoints inserted after `split_after`."""
    count = len(points)
    states = []
    for index, point in enumerate(points):
        states.append(
            (
                point.co.copy(),
                point.handle_left.copy(),
                point.handle_right.copy(),
            )
        )
        if index not in split_after:
            continue
        second = points[(index + 1) % count]
        p0, p1 = point.co, point.handle_right
        p2, p3 = second.handle_left, second.co
        q0 = (p0 + p1) * 0.5
        q1 = (p1 + p2) * 0.5
        q2 = (p2 + p3) * 0.5
        r0 = (q0 + q1) * 0.5
        r1 = (q1 + q2) * 0.5
        midpoint = (r0 + r1) * 0.5
        states.append((midpoint, r0, r1))
    return states


def _write_states(curve, states):
    curve.data.splines.remove(curve.data.splines[0])
    spline = curve.data.splines.new("BEZIER")
    spline.use_cyclic_u = True
    spline.bezier_points.add(len(states) - 1)
    for point, (co, left, right) in zip(spline.bezier_points, states):
        point.co = co
        point.handle_left_type = "FREE"
        point.handle_right_type = "FREE"
        point.handle_left = left
        point.handle_right = right
    curve.data.update_tag()
    return spline


def _densify(context, curve, scan, lines):
    """Split long intervals; snap only the new midpoints onto the body."""
    fit = trimline_ops._radial_fit_context(context, curve, scan)
    for _pass in range(4):
        spline = curve.data.splines[0]
        points = spline.bezier_points
        count = len(points)
        if count >= CONTROL_CAP:
            break
        long_pairs = {
            index
            for index in range(count)
            if (points[(index + 1) % count].co - points[index].co).length
            > SPACING_CAP_M
        }
        if not long_pairs:
            break
        allowed = max(0, CONTROL_CAP - count)
        split_after = set(sorted(long_pairs)[:allowed])
        states = _subdivided_states(points, split_after)
        inserted = []
        position = 0
        for index in range(count):
            position += 1
            if index in split_after:
                inserted.append(position)
                position += 1
        spline = _write_states(curve, states)
        points = spline.bezier_points
        for index in inserted:
            point = points[index]
            fitted = trimline_ops._radial_surface_world(
                fit, curve.matrix_world @ point.co
            )
            if fitted is None:
                continue
            delta = curve.matrix_world.inverted() @ fitted - point.co
            point.co += delta
            point.handle_left += delta
            point.handle_right += delta
        lines.append(
            f"  densify pass: {count} -> {len(points)} controls "
            f"({len(inserted)} inserted on-body)"
        )
    return curve.data.splines[0]


def _spacing_stats(spline):
    points = spline.bezier_points
    count = len(points)
    spacing = sorted(
        (points[(index + 1) % count].co - points[index].co).length
        for index in range(count)
    )
    return spacing[0] * 1000.0, spacing[-1] * 1000.0, spacing[-1] / max(
        spacing[0], 1e-9
    )


def _corner_indices(perimeter):
    half = float(perimeter.get("rigo_trim_opening_deg", 10.0)) / 2.0
    matrix = perimeter.matrix_world
    points = perimeter.data.splines[0].bezier_points
    thetas = [
        math.degrees(
            trimline_ops._curve_angle(matrix @ point.co, *(
                tuple(perimeter.get("rigo_trim_axis", (0.0, 0.0))),
                tuple(perimeter.get("rigo_trim_front", (0.0, -1.0))),
            ))
        )
        for point in points
    ]
    return sorted(
        range(len(points)), key=lambda i: abs(abs(thetas[i]) - half)
    )[:4]


def _min_non_adjacent_gap(points):
    count = len(points)
    skip = max(4, count // 20)
    best = math.inf
    step = max(1, count // 600)
    for i in range(0, count, step):
        for j in range(0, count, step):
            separation = min((j - i) % count, (i - j) % count)
            if separation < skip:
                continue
            best = min(best, (points[i] - points[j]).length)
    return best


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

        ratio_before = _junction_ratio(perimeter)
        gap95_before, gapmax_before = _displayed_vs_built(perimeter)
        spacing_before = _spacing_stats(perimeter.data.splines[0])
        lines.append(
            f"BEFORE: controls={len(perimeter.data.splines[0].bezier_points)} "
            f"spacing {spacing_before[0]:.1f}-{spacing_before[1]:.1f}mm "
            f"({spacing_before[2]:.1f}x) junction_ratio={ratio_before:.2f} "
            f"displayed-vs-built p95={gap95_before:.3f} max={gapmax_before:.3f}mm"
        )
        corners = _corner_indices(perimeter)
        corner_before = [
            perimeter.data.splines[0].bezier_points[i].co.copy()
            for i in corners
        ]

        spline = _densify(bpy.context, perimeter, scan, lines)
        _bessel_handles(spline)
        perimeter.data.update_tag()
        bpy.context.view_layer.update()

        ratio_after = _junction_ratio(perimeter)
        gap95_after, gapmax_after = _displayed_vs_built(perimeter)
        spacing_after = _spacing_stats(spline)
        lines.append(
            f"AFTER:  controls={len(spline.bezier_points)} "
            f"spacing {spacing_after[0]:.1f}-{spacing_after[1]:.1f}mm "
            f"({spacing_after[2]:.1f}x) junction_ratio={ratio_after:.2f} "
            f"displayed-vs-built p95={gap95_after:.3f} max={gapmax_after:.3f}mm"
        )
        corner_moves = [
            (
                perimeter.data.splines[0].bezier_points[index].co
                - before
            ).length
            * 1000.0
            for index, before in zip(_corner_indices(perimeter), corner_before)
        ]
        lines.append(
            f"  corner stations moved: max {max(corner_moves):.4f}mm "
            f"(pin gate <=0.5mm)"
        )
        dense = curve_build_ops._curve_world_samples(perimeter)
        self_gap = _min_non_adjacent_gap(dense) * 1000.0
        lines.append(f"  min non-adjacent self-gap={self_gap:.2f}mm (>3 required)")

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
        ok = (
            ratio_after <= 3.0
            and gap95_after <= 1.0
            and gapmax_after <= 2.0
            and max(corner_moves) <= 0.5
            and self_gap > 3.0
            and result == {"FINISHED"}
        )
        lines.append(f"PROTO_PASS={ok}")
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
        lines.append("PROTO_PASS=False")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
