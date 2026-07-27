"""P2 variant probe: ONE variant per Blender process.

trimp2proto3 tried four variants in one session and Blender died with
`Calloc returns null` in BVHNodeBV - four Generates of a 68k-vertex brace each
push a full undo snapshot, so the session ran out of address space. Each
variant therefore gets its own process, the way rimshot.py already does it.

    RIGO_P2_VARIANT = baseline | c2 | c2r06 | c2r12 | c2r24

  baseline  untouched generated template
  c2        global periodic C2 tangent solve only (no station change)
  c2rNN     C2 + balanced refinement at NN/10 mm sagitta tolerance
            (halve EVERY over-tolerance segment per pass, so spacing stays
            uniform and every original station survives exactly)

Writes trimp2var_<variant>.txt; quits Blender itself.
"""

import math
import os
import sys
import traceback

import bpy
from mathutils.bvhtree import BVHTree
from mathutils.geometry import interpolate_bezier
from mathutils.kdtree import KDTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    trimline_ops,
)

VARIANT = os.environ.get("RIGO_P2_VARIANT", "c2")
OUT = rf"C:\Projects\Blender Add-on Braces\trimp2var_{VARIANT}.txt"
TRIES = {"n": 0}
CAP = {}
CONTROL_CAP = 120

_orig_projected = curve_build_ops._projected_samples


def _projected_spy(base, perimeter):
    coordinates, normals = _orig_projected(base, perimeter)
    matrix = base.matrix_world
    normal_matrix = matrix.inverted().transposed().to_3x3()
    CAP["projected"] = [matrix @ c for c in coordinates]
    CAP["projected_normals"] = [(normal_matrix @ n).normalized() for n in normals]
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
    count = len(coordinates)
    spans = [
        max((coordinates[(i + 1) % count] - coordinates[i]).length, 1.0e-9)
        for i in range(count)
    ]
    right_hand = [
        (
            (coordinates[i] - coordinates[i - 1]) * (spans[i] / spans[i - 1])
            + (coordinates[(i + 1) % count] - coordinates[i])
            * (spans[i - 1] / spans[i])
        )
        * 3.0
        for i in range(count)
    ]
    tangents = [
        (coordinates[(i + 1) % count] - coordinates[i - 1]).normalized()
        for i in range(count)
    ]
    for _pass in range(passes):
        for i in range(count):
            tangents[i] = (
                right_hand[i]
                - tangents[i - 1] * spans[i]
                - tangents[(i + 1) % count] * spans[i - 1]
            ) / (2.0 * (spans[i - 1] + spans[i]))
    return tangents, spans


def _apply_c2_handles(spline):
    points = spline.bezier_points
    coordinates = [point.co.copy() for point in points]
    tangents, spans = _periodic_c2_tangents(coordinates)
    for i, point in enumerate(points):
        point.handle_left_type = "FREE"
        point.handle_right_type = "FREE"
        point.handle_right = coordinates[i] + tangents[i] * (spans[i] / 3.0)
        point.handle_left = coordinates[i] - tangents[i] * (spans[i - 1] / 3.0)


def _segment_midpoint(points, index):
    count = len(points)
    second = points[(index + 1) % count]
    p0, p1 = points[index].co, points[index].handle_right
    p2, p3 = second.handle_left, second.co
    q0, q1, q2 = (p0 + p1) * 0.5, (p1 + p2) * 0.5, (p2 + p3) * 0.5
    r0, r1 = (q0 + q1) * 0.5, (q1 + q2) * 0.5
    return (r0 + r1) * 0.5


def _split_segments(curve, split_indices):
    spline = curve.data.splines[0]
    points = spline.bezier_points
    count = len(points)
    states, inserted = [], []
    for i, point in enumerate(points):
        states.append(
            (point.co.copy(), point.handle_left.copy(), point.handle_right.copy())
        )
        if i not in split_indices:
            continue
        second = points[(i + 1) % count]
        p0, p1 = point.co, point.handle_right
        p2, p3 = second.handle_left, second.co
        q0, q1, q2 = (p0 + p1) * 0.5, (p1 + p2) * 0.5, (p2 + p3) * 0.5
        r0, r1 = (q0 + q1) * 0.5, (q1 + q2) * 0.5
        inserted.append(len(states))
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
    return inserted


def _refine_balanced(context, curve, scan, bvh, tolerance, lines):
    fit = trimline_ops._radial_fit_context(context, curve, scan)
    total = 0
    for _pass in range(5):
        spline = curve.data.splines[0]
        points = spline.bezier_points
        if len(points) >= CONTROL_CAP:
            break
        over = set()
        for index in range(len(points)):
            world = curve.matrix_world @ _segment_midpoint(points, index)
            fitted = trimline_ops._nearest_surface_world(scan, bvh, world)
            if fitted is not None and (world - fitted).length > tolerance:
                over.add(index)
        if not over:
            break
        allowed = CONTROL_CAP - len(points)
        if len(over) > allowed:
            over = set(sorted(over)[:allowed])
        inserted = _split_segments(curve, over)
        new_points = curve.data.splines[0].bezier_points
        for index in inserted:
            point = new_points[index]
            fitted = trimline_ops._radial_surface_world(
                fit, curve.matrix_world @ point.co
            )
            if fitted is None:
                continue
            delta = curve.matrix_world.inverted() @ fitted - point.co
            point.co += delta
            point.handle_left += delta
            point.handle_right += delta
        _apply_c2_handles(curve.data.splines[0])
        total += len(inserted)
    lines.append(f"  refinement: +{total} stations at {tolerance*1000:.1f}mm")


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


def _spacing(spline):
    points = spline.bezier_points
    count = len(points)
    values = sorted(
        (points[(i + 1) % count].co - points[i].co).length for i in range(count)
    )
    return values[0] * 1000.0, values[-1] * 1000.0, values[-1] / max(values[0], 1e-9)


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


def _corner_positions(perimeter):
    half = float(perimeter.get("rigo_trim_opening_deg", 10.0)) / 2.0
    axis = tuple(perimeter.get("rigo_trim_axis", (0.0, 0.0)))
    front = tuple(perimeter.get("rigo_trim_front", (0.0, -1.0)))
    matrix = perimeter.matrix_world
    points = perimeter.data.splines[0].bezier_points
    thetas = [
        math.degrees(trimline_ops._curve_angle(matrix @ p.co, axis, front))
        for p in points
    ]
    order = sorted(range(len(points)), key=lambda i: abs(abs(thetas[i]) - half))
    return [(matrix @ points[i].co).copy() for i in order[:4]]


def _corner_drift(perimeter, recorded):
    matrix = perimeter.matrix_world
    controls = [matrix @ p.co for p in perimeter.data.splines[0].bezier_points]
    return max(
        min((control - corner).length for control in controls) * 1000.0
        for corner in recorded
    )


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = [f"variant={VARIANT}"]
    try:
        curve_build_ops._projected_samples = _projected_spy
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        perimeter = bpy.data.objects["Rigo Trim Perimeter"]
        corners = _corner_positions(perimeter)

        if VARIANT != "baseline":
            _apply_c2_handles(perimeter.data.splines[0])
            if VARIANT.startswith("c2r"):
                tolerance = int(VARIANT[3:]) * 0.0001
                bvh = BVHTree.FromObject(
                    scan, bpy.context.evaluated_depsgraph_get()
                )
                _refine_balanced(
                    bpy.context, perimeter, scan, bvh, tolerance, lines
                )
            perimeter.data.update_tag()
            bpy.context.view_layer.update()

        ratio, jump, base = _junction_ratio(perimeter.data.splines[0])
        raw95, rawmax = _display_vs_raw(perimeter)
        spacing = _spacing(perimeter.data.splines[0])
        drift = _corner_drift(perimeter, corners)
        dense = curve_build_ops._curve_world_samples(perimeter)
        gap = _min_non_adjacent_gap(dense) * 1000.0
        turns = sorted(
            math.degrees(
                (dense[i] - dense[i - 1]).angle(
                    dense[(i + 1) % len(dense)] - dense[i]
                )
            )
            for i in range(len(dense))
            if (dense[i] - dense[i - 1]).length > 1e-9
            and (dense[(i + 1) % len(dense)] - dense[i]).length > 1e-9
        )
        lines.append(
            f"  controls={len(perimeter.data.splines[0].bezier_points)} "
            f"spacing {spacing[0]:.1f}-{spacing[1]:.1f}mm ({spacing[2]:.1f}x)"
        )
        lines.append(
            f"  junction_ratio={ratio:.2f} (jump {jump:.1f} / base {base:.2f})"
        )
        lines.append(
            f"  display-vs-raw p95={raw95:.3f} max={rawmax:.3f}mm "
            f"corner_drift={drift:.4f}mm self_gap={gap:.2f}mm "
            f"turn p95={_pct(turns, 0.95):.2f} max={turns[-1]:.2f}deg"
        )
        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result, error = {"CANCELLED"}, str(exc).strip()[:130]
        lines.append(f"  generate={result} {error}")
        corset = bpy.data.objects.get("Rigo Corset")
        if result == {"FINISHED"} and corset is not None:
            lines.append(
                f"  corset: verts={len(corset.data.vertices)} "
                f"intersections={corset.get('rigo_generation_rim_intersections')} "
                f"zero_area={corset.get('rigo_generation_zero_area_faces')} "
                f"trim p95={corset.get('rigo_trim_curve_p95_error_mm', -1):.4f} "
                f"max={corset.get('rigo_trim_curve_max_error_mm', -1):.4f}mm "
                f"fillet={corset.get('rigo_trim_fillet_mean_radius_mm', -1):.3f}mm"
            )
            built = _display_vs_built(perimeter)
            if built is not None:
                lines.append(
                    f"  DISPLAY vs BUILT total p95={built[0]:.3f} "
                    f"max={built[1]:.3f}mm | tangential p95={built[2]:.3f} "
                    f"max={built[3]:.3f}mm"
                )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    finally:
        curve_build_ops._projected_samples = _orig_projected
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
