"""Upstream trimline audit: generator curve quality, editor mechanics, lifecycle.

The downstream stages (projection -> cut -> resample -> rim) are measured by
rimwavedbg.py. This script measures everything UPSTREAM of projection plus the
object lifecycle, answering the template-trimline audit brief:

  A  object lifecycle - which curve/mesh objects exist, visibility, duplicates
     on regeneration, and the build-preview tube's relationship to the shell
  B  clinical Bezier fairness - control spacing, turn angles, curvature
     distribution, junction (control-point) continuity G1/G2, handle reach
     vs Catmull-Rom, opening-edge straightness, per-view projected fairness
  C  editor mechanics - Fit drift, drag locality/tent boundary, custom-handle
     wipe, refine (subdivide+radial refit) fidelity

Writes trimgenaudit_result.txt; quits Blender itself.
"""

import math
import sys
import traceback

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import interpolate_bezier
from mathutils.kdtree import KDTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    trimline_ops,
)

OUT = r"C:\Projects\Blender Add-on Braces\trimgenaudit_result.txt"
TRIES = {"n": 0}


def _pct(sorted_values, fraction):
    if not sorted_values:
        return 0.0
    return sorted_values[int(fraction * (len(sorted_values) - 1))]


def _turn_radius(a, b, c):
    first, second, third = (b - a).length, (c - b).length, (c - a).length
    if min(first, second, third) <= 1e-12:
        return math.inf
    half = (first + second + third) * 0.5
    area_sq = max(half * (half - first) * (half - second) * (half - third), 0.0)
    if area_sq <= 1e-24:
        return math.inf
    return (first * second * third) / (4.0 * math.sqrt(area_sq))


def _curvature(a, b, c):
    radius = _turn_radius(a, b, c)
    return 0.0 if radius == math.inf else 1.0 / radius


def _turn_angles(points):
    count = len(points)
    angles = []
    for index in range(count):
        entering = points[index] - points[index - 1]
        leaving = points[(index + 1) % count] - points[index]
        if min(entering.length, leaving.length) > 1e-12:
            angles.append(math.degrees(entering.angle(leaving)))
        else:
            angles.append(0.0)
    return angles


def _spacing(points):
    count = len(points)
    return sorted(
        (points[(index + 1) % count] - points[index]).length
        for index in range(count)
    )


def _perimeter():
    return bpy.data.objects["Rigo Trim Perimeter"]


def _dense(perimeter):
    return curve_build_ops._curve_world_samples(perimeter)


def _controls_world(perimeter):
    matrix = perimeter.matrix_world
    return [
        matrix @ point.co
        for point in perimeter.data.splines[0].bezier_points
    ]


def _scan_normal_world(scan, bvh, world_point):
    inverse = scan.matrix_world.inverted()
    hit = bvh.find_nearest(inverse @ world_point)
    if hit[0] is None:
        return None
    normal_matrix = inverse.transposed().to_3x3()
    return (normal_matrix @ hit[1]).normalized()


def _describe_curve(label, dense, lines):
    spacing = _spacing(dense)
    angles = sorted(_turn_angles(dense))
    total = sum(spacing)
    lines.append(
        f"{label}: n={len(dense)} length={total*1000:.0f}mm "
        f"spacing_mm min={spacing[0]*1000:.3f} "
        f"p50={_pct(spacing, 0.5)*1000:.3f} max={spacing[-1]*1000:.3f}"
    )
    lines.append(
        f"    turn_deg p50={_pct(angles, 0.5):.3f} p95={_pct(angles, 0.95):.3f} "
        f"p99={_pct(angles, 0.99):.3f} max={angles[-1]:.3f}"
    )
    curvatures = sorted(
        _curvature(dense[i - 1], dense[i], dense[(i + 1) % len(dense)])
        for i in range(len(dense))
    )
    lines.append(
        f"    curvature_1_per_m p50={_pct(curvatures, 0.5):.1f} "
        f"p95={_pct(curvatures, 0.95):.1f} max={curvatures[-1]:.1f} "
        f"(tightest radius {1000.0/max(curvatures[-1], 1e-9):.1f}mm)"
    )


def _fairness_flips(dense, scan, bvh, lines, sigma_m=0.003):
    from bl_ext.user_default.rigo_brace.operators.custom_trim_ops import (
        _smooth_closed_parametric,
    )

    count = len(dense)
    spacing = sum(_spacing(dense)) / count
    smooth = _smooth_closed_parametric(dense, sigma_m, spacing)
    offsets = []
    for index in range(count):
        tangent = smooth[(index + 1) % count] - smooth[index - 1]
        if tangent.length <= 1e-12:
            offsets.append(0.0)
            continue
        tangent.normalize()
        normal = _scan_normal_world(scan, bvh, smooth[index])
        if normal is None:
            offsets.append(0.0)
            continue
        binormal = tangent.cross(normal)
        if binormal.length <= 1e-12:
            offsets.append(0.0)
            continue
        offsets.append((dense[index] - smooth[index]).dot(binormal.normalized()))
    flips = sum(1 for i in range(count) if offsets[i] * offsets[i - 1] < 0.0)
    magnitude = sorted(abs(value) for value in offsets)
    rms = math.sqrt(sum(value * value for value in offsets) / count)
    lines.append(
        f"    lateral offset from own {sigma_m*1000:.0f}mm-smoothed self: "
        f"p50={_pct(magnitude, 0.5)*1000:.4f}mm p95={_pct(magnitude, 0.95)*1000:.4f}mm "
        f"max={magnitude[-1]*1000:.4f}mm rms={rms*1000:.4f}mm "
        f"sign_flips={flips} ({100.0*flips/count:.1f}%)"
    )


def _junction_continuity(perimeter, lines):
    points = perimeter.data.splines[0].bezier_points
    count = len(points)
    segments = []
    for index in range(count):
        first = points[index]
        second = points[(index + 1) % count]
        segments.append(
            interpolate_bezier(
                first.co, first.handle_right, second.handle_left, second.co, 65
            )
        )
    tangent_breaks = []
    curvature_jumps = []
    within_segment_steps = []
    per_junction = []
    for index in range(count):
        previous = segments[index - 1]
        current = segments[index]
        end_tangent = previous[64] - previous[63]
        start_tangent = current[1] - current[0]
        if min(end_tangent.length, start_tangent.length) > 1e-12:
            tangent_breaks.append(
                math.degrees(end_tangent.angle(start_tangent))
            )
        k_end = _curvature(previous[62], previous[63], previous[64])
        k_start = _curvature(current[0], current[1], current[2])
        curvature_jumps.append(abs(k_start - k_end))
        per_junction.append((abs(k_start - k_end), index))
        for sample in range(1, 63):
            k_here = _curvature(
                current[sample - 1], current[sample], current[sample + 1]
            )
            k_next = _curvature(
                current[sample], current[sample + 1], current[sample + 2]
            )
            within_segment_steps.append(abs(k_next - k_here))
    tangent_breaks.sort()
    jumps = sorted(curvature_jumps)
    within = sorted(within_segment_steps)
    lines.append(
        f"  junction tangent break deg: p50={_pct(tangent_breaks, 0.5):.4f} "
        f"p95={_pct(tangent_breaks, 0.95):.4f} max={tangent_breaks[-1]:.4f} "
        f"(G1 if ~0)"
    )
    lines.append(
        f"  junction curvature jump 1/m: p50={_pct(jumps, 0.5):.1f} "
        f"p95={_pct(jumps, 0.95):.1f} max={jumps[-1]:.1f}"
    )
    lines.append(
        f"  within-segment curvature step 1/m (baseline): "
        f"p50={_pct(within, 0.5):.2f} p95={_pct(within, 0.95):.2f} "
        f"max={within[-1]:.2f}"
    )
    worst = sorted(per_junction, reverse=True)[:6]
    axis = tuple(perimeter.get("rigo_trim_axis", (0.0, 0.0)))
    front = tuple(perimeter.get("rigo_trim_front", (0.0, -1.0)))
    matrix = perimeter.matrix_world
    for jump, index in worst:
        world = matrix @ points[index].co
        theta = math.degrees(
            trimline_ops._curve_angle(world, axis, front)
        )
        lines.append(
            f"    worst junction jump {jump:.1f} 1/m at control {index} "
            f"theta={theta:.1f}deg z={world.z*1000:.0f}mm"
        )


def _handle_reach(perimeter, lines):
    points = perimeter.data.splines[0].bezier_points
    count = len(points)
    ratios = []
    for index, point in enumerate(points):
        chord_prev = (point.co - points[index - 1].co).length
        chord_next = (points[(index + 1) % count].co - point.co).length
        reach = (point.handle_right - point.co).length
        if chord_next > 1e-12:
            ratios.append(reach / (chord_next / 3.0))
    ratios.sort()
    lines.append(
        f"  handle reach vs Catmull-Rom third-of-chord: "
        f"min={ratios[0]:.3f} p50={_pct(ratios, 0.5):.3f} "
        f"max={ratios[-1]:.3f} (1.0 = standard interpolation)"
    )


def _high_turn_points(perimeter, dense, lines):
    axis = tuple(perimeter.get("rigo_trim_axis", (0.0, 0.0)))
    front = tuple(perimeter.get("rigo_trim_front", (0.0, -1.0)))
    opening_deg = float(perimeter.get("rigo_trim_opening_deg", 10.0))
    angles = _turn_angles(dense)
    high = [
        (angle, index) for index, angle in enumerate(angles) if angle > 10.0
    ]
    intentional = 0
    accidental = []
    for angle, index in high:
        theta = abs(
            math.degrees(
                trimline_ops._curve_angle(dense[index], axis, front)
            )
        )
        if theta < opening_deg * 1.5:
            intentional += 1
        else:
            accidental.append((angle, index, theta))
    lines.append(
        f"  high-turn dense samples (>10deg): {len(high)} total, "
        f"{intentional} at the opening (theta < {opening_deg*1.5:.1f}deg = intentional), "
        f"{len(accidental)} elsewhere (accidental)"
    )
    for angle, index, theta in sorted(accidental, reverse=True)[:5]:
        lines.append(
            f"    accidental turn {angle:.1f}deg at sample {index} "
            f"theta={theta:.1f}deg z={dense[index].z*1000:.0f}mm"
        )


def _opening_edge_straightness(perimeter, dense, lines):
    axis = tuple(perimeter.get("rigo_trim_axis", (0.0, 0.0)))
    front = tuple(perimeter.get("rigo_trim_front", (0.0, -1.0)))
    opening_deg = float(perimeter.get("rigo_trim_opening_deg", 10.0))
    half = opening_deg / 2.0
    for side, sign in (("right", 1.0), ("left", -1.0)):
        members = [
            point
            for point in dense
            if abs(
                math.degrees(trimline_ops._curve_angle(point, axis, front))
                - sign * half
            )
            < half * 0.6
        ]
        if len(members) < 8:
            lines.append(f"  opening edge {side}: too few samples")
            continue
        centroid = sum(members, Vector()) / len(members)
        moments = [point - centroid for point in members]
        direction = Vector((0.0, 0.0, 1.0))
        for _power in range(24):
            accumulated = Vector()
            for moment in moments:
                accumulated += moment * moment.dot(direction)
            if accumulated.length <= 1e-12:
                break
            direction = accumulated.normalized()
        laterals = sorted(
            (moment - direction * moment.dot(direction)).length
            for moment in moments
        )
        span = max(abs(moment.dot(direction)) for moment in moments) * 2.0
        lines.append(
            f"  opening edge {side}: n={len(members)} span={span*1000:.0f}mm "
            f"lateral-from-best-line p50={_pct(laterals, 0.5)*1000:.2f}mm "
            f"p95={_pct(laterals, 0.95)*1000:.2f}mm max={laterals[-1]*1000:.2f}mm"
        )


def _view_fairness(dense, lines):
    for view, keep in (("top_XY", (0, 1)), ("front_XZ", (0, 2)), ("side_YZ", (1, 2))):
        flat = [
            Vector((point[keep[0]], point[keep[1]], 0.0)) for point in dense
        ]
        angles = []
        count = len(flat)
        for index in range(count):
            entering = flat[index] - flat[index - 1]
            leaving = flat[(index + 1) % count] - flat[index]
            if min(entering.length, leaving.length) > 2e-4:
                angles.append(math.degrees(entering.angle(leaving)))
        angles.sort()
        lines.append(
            f"  {view}: turn_deg p50={_pct(angles, 0.5):.3f} "
            f"p95={_pct(angles, 0.95):.3f} max={angles[-1]:.2f} "
            f"(n={len(angles)})"
        )


def _snapshot_objects(lines, header):
    lines.append(header)
    for obj in sorted(bpy.data.objects, key=lambda o: o.name):
        if obj.type not in {"CURVE", "MESH"}:
            continue
        extras = []
        if obj.type == "CURVE":
            extras.append(f"bevel={obj.data.bevel_depth*1000:.1f}mm")
            extras.append(
                f"controls={sum(len(s.bezier_points) for s in obj.data.splines)}"
            )
        for modifier in obj.modifiers:
            target = getattr(modifier, "target", None)
            extras.append(
                f"{modifier.type}->{target.name if target else '-'}"
            )
        lines.append(
            f"    {obj.name!r} {obj.type} "
            f"{'HIDDEN' if obj.hide_get() else 'visible'} "
            f"{' '.join(extras)}"
        )


def _curve_centerline_world(obj):
    bevel = obj.data.bevel_depth
    obj.data.bevel_depth = 0.0
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    points = [obj.matrix_world @ vertex.co for vertex in mesh.vertices]
    evaluated.to_mesh_clear()
    obj.data.bevel_depth = bevel
    return points


def _distance_stats(points, target_obj, lines, label):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    bvh = BVHTree.FromObject(target_obj, depsgraph)
    inverse = target_obj.matrix_world.inverted()
    distances = []
    for point in points:
        hit = bvh.find_nearest(inverse @ point)
        if hit[0] is None:
            distances.append(math.inf)
        else:
            distances.append(((target_obj.matrix_world @ hit[0]) - point).length)
    distances.sort()
    lines.append(
        f"  {label}: n={len(points)} distance_mm min={distances[0]*1000:.3f} "
        f"p50={_pct(distances, 0.5)*1000:.3f} max={distances[-1]*1000:.3f}"
    )
    return distances


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = []
    try:
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        depsgraph = bpy.context.evaluated_depsgraph_get()
        scan_bvh = BVHTree.FromObject(scan, depsgraph)
        perimeter = _perimeter()

        lines.append("=== B  CLINICAL BEZIER (generated template, pre-projection) ===")
        controls = _controls_world(perimeter)
        control_spacing = _spacing(controls)
        control_angles = sorted(_turn_angles(controls))
        lines.append(
            f"  controls n={len(controls)} spacing_mm min={control_spacing[0]*1000:.1f} "
            f"p50={_pct(control_spacing, 0.5)*1000:.1f} max={control_spacing[-1]*1000:.1f}"
        )
        lines.append(
            f"  control-polygon turn_deg p50={_pct(control_angles, 0.5):.1f} "
            f"p95={_pct(control_angles, 0.95):.1f} max={control_angles[-1]:.1f}"
        )
        dense = _dense(perimeter)
        _describe_curve("  dense evaluated (raw bezier)", dense, lines)
        _fairness_flips(dense, scan, scan_bvh, lines)
        _junction_continuity(perimeter, lines)
        _handle_reach(perimeter, lines)
        _high_turn_points(perimeter, dense, lines)
        _opening_edge_straightness(perimeter, dense, lines)
        _view_fairness(dense, lines)

        # Displayed (shrinkwrapped) line vs the raw bezier that Generate samples
        displayed = _curve_centerline_world(perimeter)
        tree = KDTree(len(dense))
        for index, point in enumerate(dense):
            tree.insert(point, index)
        tree.balance()
        gaps = sorted(tree.find(point)[2] for point in displayed)
        lines.append(
            f"  displayed(shrinkwrap-evaluated) vs raw-bezier gap_mm "
            f"p50={_pct(gaps, 0.5)*1000:.3f} p95={_pct(gaps, 0.95)*1000:.3f} "
            f"max={gaps[-1]*1000:.3f}"
        )

        lines.append("")
        lines.append("=== C  EDITOR MECHANICS ===")
        spline = perimeter.data.splines[0]
        points = spline.bezier_points

        # C3: Fit Line to Body on an untouched curve - pure snap drift
        before_fit = [point.co.copy() for point in points]
        fitted, moved = trimline_ops._fit_curve_points(
            bpy.context, perimeter, scan
        )
        drift = sorted(
            (point.co - old).length for point, old in zip(points, before_fit)
        )
        lines.append(
            f"  C3 Fit-to-body on untouched curve: fitted={fitted} moved={moved} "
            f"drift_mm p50={_pct(drift, 0.5)*1000:.4f} max={drift[-1]*1000:.4f}"
        )

        # Reset to a clean generated curve
        bpy.ops.rigo.auto_trimline()
        perimeter = _perimeter()
        spline = perimeter.data.splines[0]
        points = spline.bezier_points
        count = len(points)
        matrix = perimeter.matrix_world
        inverse_matrix = matrix.inverted()
        axis = tuple(perimeter.get("rigo_trim_axis", (0.0, 0.0)))
        front = tuple(perimeter.get("rigo_trim_front", (0.0, -1.0)))

        # pick the drag point nearest theta=180deg (patient back)
        def _theta_of_control(index):
            return math.degrees(
                trimline_ops._curve_angle(matrix @ points[index].co, axis, front)
            )

        drag_index = min(
            range(count), key=lambda i: abs(abs(_theta_of_control(i)) - 180.0)
        )
        far_index = min(
            range(count), key=lambda i: abs(_theta_of_control(i) - 90.0)
        )

        # C1: user rotates a far handle, then drags a control elsewhere
        far_point = points[far_index]
        pre_rotation = (far_point.handle_right - far_point.co).normalized()
        normal = _scan_normal_world(scan, scan_bvh, matrix @ far_point.co)
        from mathutils import Matrix

        rotation = Matrix.Rotation(math.radians(20.0), 4, normal)
        far_point.handle_left_type = "FREE"
        far_point.handle_right_type = "FREE"
        far_point.handle_left = far_point.co + rotation @ (
            far_point.handle_left - far_point.co
        )
        far_point.handle_right = far_point.co + rotation @ (
            far_point.handle_right - far_point.co
        )
        perimeter["rigo_trim_handle_model"] = "LINKED_TANGENTS"
        rotated = (far_point.handle_right - far_point.co).normalized()
        dense_before = _dense(perimeter)

        # replicate RIGO_OT_slide_trimline_on_surface._move_dragged_point
        drag_point = points[drag_index]
        start_states = [
            (point.co.copy(), point.handle_left.copy(), point.handle_right.copy())
            for point in points
        ]
        drag_world = matrix @ drag_point.co
        drag_normal = _scan_normal_world(scan, scan_bvh, drag_world)
        move_direction = Vector((0.0, 0.0, 1.0))
        move_direction -= drag_normal * move_direction.dot(drag_normal)
        move_direction.normalize()
        target_world = drag_world + move_direction * 0.008
        delta = (inverse_matrix @ target_world) - start_states[drag_index][0]
        affected = {}
        for offset, weight in ((0, 1.0), (-1, 0.50), (1, 0.50), (-2, 0.18), (2, 0.18)):
            index = (drag_index + offset) % count
            affected[index] = max(weight, affected.get(index, 0.0))
        for index, weight in affected.items():
            intended = start_states[index][0] + delta * weight
            fitted_world = trimline_ops._nearest_surface_world(
                scan, scan_bvh, matrix @ intended
            )
            if fitted_world is not None:
                points[index].co = inverse_matrix @ fitted_world
        trimline_ops._set_clamped_tangent_handles(spline)
        perimeter.data.update_tag()

        after_rotation = (far_point.handle_right - far_point.co).normalized()
        wipe_deg = math.degrees(rotated.angle(after_rotation))
        kept_deg = math.degrees(pre_rotation.angle(after_rotation))
        lines.append(
            f"  C1 handle wipe: far control ({far_index}, theta 90deg) handle was "
            f"user-rotated 20deg; after dragging control {drag_index} "
            f"(theta 180deg) the far handle moved {wipe_deg:.1f}deg away from the "
            f"user's direction ({kept_deg:.1f}deg from the automatic one)"
        )

        dense_after = _dense(perimeter)
        cumulative = [0.0]
        for index in range(1, len(dense_before)):
            cumulative.append(
                cumulative[-1]
                + (dense_before[index] - dense_before[index - 1]).length
            )
        drag_dense = min(
            range(len(dense_before)),
            key=lambda i: (dense_before[i] - drag_world).length,
        )
        total = cumulative[-1]
        bands = [
            (0.0, 0.010),
            (0.010, 0.025),
            (0.025, 0.050),
            (0.050, 0.075),
            (0.075, 0.100),
            (0.100, 0.150),
            (0.150, 10.0),
        ]
        band_max = {band: 0.0 for band in bands}
        for index in range(len(dense_before)):
            arc = abs(cumulative[index] - cumulative[drag_dense])
            arc = min(arc, total - arc)
            displacement = (dense_after[index] - dense_before[index]).length
            for band in bands:
                if band[0] <= arc < band[1]:
                    band_max[band] = max(band_max[band], displacement)
        lines.append("  C2 drag response (8mm requested), max displacement by arc distance:")
        for band in bands:
            lines.append(
                f"    {band[0]*1000:.0f}-{band[1]*1000:.0f}mm: "
                f"{band_max[band]*1000:.3f}mm"
            )
        window = [
            index
            for index in range(len(dense_before))
            if min(
                abs(cumulative[index] - cumulative[drag_dense]),
                total - abs(cumulative[index] - cumulative[drag_dense]),
            )
            < 0.100
        ]
        turn_before = sorted(
            _turn_angles(dense_before)[index] for index in window
        )
        turn_after_all = _turn_angles(dense_after)
        turn_after = sorted(turn_after_all[index] for index in window)
        lines.append(
            f"    turn_deg in the 100mm window: before p95={_pct(turn_before, 0.95):.2f} "
            f"max={turn_before[-1]:.2f} -> after p95={_pct(turn_after, 0.95):.2f} "
            f"max={turn_after[-1]:.2f}"
        )

        # C4: refine (double controls + radial refit) fidelity
        bpy.ops.rigo.auto_trimline()
        perimeter = _perimeter()
        dense_pre = _dense(perimeter)
        pre_count = len(perimeter.data.splines[0].bezier_points)
        bpy.ops.rigo.refine_trimline()
        perimeter = _perimeter()
        post_count = len(perimeter.data.splines[0].bezier_points)
        dense_post = _dense(perimeter)
        tree = KDTree(len(dense_pre))
        for index, point in enumerate(dense_pre):
            tree.insert(point, index)
        tree.balance()
        deviations = sorted(tree.find(point)[2] for point in dense_post)
        angles_pre = sorted(_turn_angles(dense_pre))
        angles_post = sorted(_turn_angles(dense_post))
        lines.append(
            f"  C4 refine {pre_count}->{post_count} controls: deviation_mm "
            f"p50={_pct(deviations, 0.5)*1000:.3f} p95={_pct(deviations, 0.95)*1000:.3f} "
            f"max={deviations[-1]*1000:.3f}; turn p95 {_pct(angles_pre, 0.95):.2f} -> "
            f"{_pct(angles_post, 0.95):.2f}deg, max {angles_pre[-1]:.2f} -> "
            f"{angles_post[-1]:.2f}deg"
        )

        lines.append("")
        lines.append("=== A  OBJECT LIFECYCLE ===")
        bpy.ops.rigo.auto_trimline()
        names_once = sorted(
            obj.name for obj in bpy.data.objects if "Trim" in obj.name
        )
        bpy.ops.rigo.auto_trimline()
        names_twice = sorted(
            obj.name for obj in bpy.data.objects if "Trim" in obj.name
        )
        lines.append(
            f"  auto_trimline twice: objects {names_once} -> {names_twice} "
            f"duplicates={'NO' if names_once == names_twice else 'YES'}"
        )
        _snapshot_objects(lines, "  after auto_trimline (TRIM view):")
        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result, error = {"CANCELLED"}, str(exc).strip()[:140]
        lines.append(f"  generate #1: {result} {error}")
        _snapshot_objects(lines, "  after generate (BRACE view):")
        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result, error = {"CANCELLED"}, str(exc).strip()[:140]
        lines.append(f"  generate #2 (regeneration): {result} {error}")
        suspicious = sorted(
            obj.name
            for obj in bpy.data.objects
            if ".0" in obj.name or "Candidate" in obj.name or "Backup" in obj.name
        )
        lines.append(f"  stale/duplicate-suspect names after regenerate: {suspicious}")

        corset = bpy.data.objects.get("Rigo Corset")
        build = bpy.data.objects.get("Rigo Build Trim Perimeter")
        if corset is not None and build is not None:
            lines.append(
                f"  corset props: p95_err={corset.get('rigo_trim_curve_p95_error_mm', -1):.3f}mm "
                f"max_err={corset.get('rigo_trim_curve_max_error_mm', -1):.3f}mm "
                f"fillet_mean={corset.get('rigo_trim_fillet_mean_radius_mm', -1):.3f}mm "
                f"spacing_after={list(corset.get('rigo_rim_spacing_after_mm', []))}"
            )
            lines.append(
                f"  build-preview tube: bevel_depth={build.data.bevel_depth*1000:.2f}mm "
                f"shrinkwrap_offset={next((m.offset for m in build.modifiers if m.type=='SHRINKWRAP'), -1)*1000:.2f}mm"
            )
            centerline = _curve_centerline_world(build)
            distances = _distance_stats(
                centerline, corset, lines,
                "build-tube centerline to corset surface",
            )
            radius = build.data.bevel_depth
            inside = sum(1 for distance in distances if distance < radius)
            lines.append(
                f"  tube stretches closer to the shell than the tube radius "
                f"({radius*1000:.1f}mm): {inside}/{len(distances)} samples "
                f"({100.0*inside/len(distances):.0f}%) -> those arcs pierce the "
                f"shell surface and show as marks/doubled edges"
            )
            source_line = _curve_centerline_world(_perimeter())
            _distance_stats(
                source_line, corset, lines,
                "SOURCE perimeter (displayed in TRIM) to corset surface",
            )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
