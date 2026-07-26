"""Gate battery for the trimline patches P1-P4 (TRIMLINE_TEMPLATE_AUDIT).

Every metric is always measured and reported; each patch promotes its own
gates from REPORT to ENFORCED, so a revert of one patch only relaxes that
patch's gates. Current enforcement level: set `ENFORCED_LEVEL` below.

  P1  display truth: lifecycle/duplicates, single visible authority,
      overlay tube clearance, generate success, self-crossing clearance
  P2  generator: junction-curvature ratio, displayed-vs-built p95+max,
      opening-corner pinning, opening width
  P3  editor: influence distance in mm, manual-handle preservation
  P4  refine: exact-subdivision shape deviation

Writes trimgentest_result.txt with PASS=True/False; quits Blender itself.
"""

import math
import sys
import traceback

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import interpolate_bezier
from mathutils.kdtree import KDTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    trimline_ops,
)

OUT = r"C:\Projects\Blender Add-on Braces\trimgentest_result.txt"
TRIES = {"n": 0}

# Raise as each patch lands; a revert lowers it again.
ENFORCED_LEVEL = 1

GATES = []


def _gate(level, name, ok, detail):
    GATES.append((level, name, bool(ok), detail))


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


def _perimeter():
    return bpy.data.objects["Rigo Trim Perimeter"]


def _controls(perimeter):
    matrix = perimeter.matrix_world
    return [
        matrix @ point.co
        for point in perimeter.data.splines[0].bezier_points
    ]


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
    jumps = []
    within = []
    for i in range(count):
        previous, current = segments[i - 1], segments[i]
        k_end = _curvature(previous[62], previous[63], previous[64])
        k_start = _curvature(current[0], current[1], current[2])
        jumps.append(abs(k_start - k_end))
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


def _displayed_vs_built(perimeter):
    dense = curve_build_ops._curve_world_samples(perimeter)
    displayed = _centerline(perimeter)
    tree = KDTree(len(dense))
    for index, point in enumerate(dense):
        tree.insert(point, index)
    tree.balance()
    gaps = sorted(tree.find(point)[2] for point in displayed)
    return _pct(gaps, 0.95), gaps[-1]


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


def _theta_deg(perimeter, world):
    axis = tuple(perimeter.get("rigo_trim_axis", (0.0, 0.0)))
    front = tuple(perimeter.get("rigo_trim_front", (0.0, -1.0)))
    return math.degrees(trimline_ops._curve_angle(world, axis, front))


def _opening_measurements(perimeter):
    """(worst corner |theta| error deg, measured opening chord mm at waist)."""
    half = float(perimeter.get("rigo_trim_opening_deg", 10.0)) / 2.0
    controls = _controls(perimeter)
    thetas = [_theta_deg(perimeter, world) for world in controls]
    # The four opening corners are the four controls whose |theta| lands
    # closest to the half-opening angle; the gate is the worst of those four.
    errors = sorted(abs(abs(theta) - half) for theta in thetas)
    corner_error = errors[3] if len(errors) >= 4 else math.inf
    dense = curve_build_ops._curve_world_samples(perimeter)
    z_values = sorted(point.z for point in dense)
    z_waist = _pct(z_values, 0.5)
    sides = {1.0: [], -1.0: []}
    for point in dense:
        theta = _theta_deg(perimeter, point)
        for sign in (1.0, -1.0):
            if abs(theta - sign * half) < half * 0.5:
                sides[sign].append(point)
    chord = math.inf
    if sides[1.0] and sides[-1.0]:
        near_right = min(sides[1.0], key=lambda p: abs(p.z - z_waist))
        near_left = min(sides[-1.0], key=lambda p: abs(p.z - z_waist))
        chord = (near_right - near_left).length * 1000.0
    return corner_error, chord


def _scan_normal_world(scan, bvh, world_point):
    inverse = scan.matrix_world.inverted()
    hit = bvh.find_nearest(inverse @ world_point)
    if hit[0] is None:
        return None
    return ((inverse.transposed().to_3x3()) @ hit[1]).normalized()


def _drag_experiment(scan, scan_bvh, lines):
    """Replicates the point-drag path; returns (far_move_mm, wipe_deg)."""
    bpy.ops.rigo.auto_trimline()
    perimeter = _perimeter()
    spline = perimeter.data.splines[0]
    points = spline.bezier_points
    count = len(points)
    matrix = perimeter.matrix_world
    inverse_matrix = matrix.inverted()

    def theta(i):
        return _theta_deg(perimeter, matrix @ points[i].co)

    drag_index = min(range(count), key=lambda i: abs(abs(theta(i)) - 180.0))
    far_index = min(range(count), key=lambda i: abs(theta(i) - 90.0))

    far_point = points[far_index]
    normal = _scan_normal_world(scan, scan_bvh, matrix @ far_point.co)
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

    dense_before = curve_build_ops._curve_world_samples(perimeter)
    start_states = [
        (p.co.copy(), p.handle_left.copy(), p.handle_right.copy())
        for p in points
    ]
    drag_world = matrix @ points[drag_index].co
    drag_normal = _scan_normal_world(scan, scan_bvh, drag_world)
    direction = Vector((0.0, 0.0, 1.0))
    direction -= drag_normal * direction.dot(drag_normal)
    direction.normalize()
    target_world = drag_world + direction * 0.008
    delta = (inverse_matrix @ target_world) - start_states[drag_index][0]
    affected = {}
    for offset, weight in ((0, 1.0), (-1, 0.50), (1, 0.50), (-2, 0.18), (2, 0.18)):
        index = (drag_index + offset) % count
        affected[index] = max(weight, affected.get(index, 0.0))
    for index, weight in affected.items():
        intended = start_states[index][0] + delta * weight
        fitted = trimline_ops._nearest_surface_world(
            scan, scan_bvh, matrix @ intended
        )
        if fitted is not None:
            points[index].co = inverse_matrix @ fitted
    trimline_ops._set_clamped_tangent_handles(spline)
    perimeter.data.update_tag()

    after = (far_point.handle_right - far_point.co).normalized()
    wipe_deg = math.degrees(rotated.angle(after))

    dense_after = curve_build_ops._curve_world_samples(perimeter)
    cumulative = [0.0]
    for index in range(1, len(dense_before)):
        cumulative.append(
            cumulative[-1]
            + (dense_before[index] - dense_before[index - 1]).length
        )
    total = cumulative[-1]
    origin = min(
        range(len(dense_before)),
        key=lambda i: (dense_before[i] - drag_world).length,
    )
    far_move = 0.0
    for index in range(len(dense_before)):
        arc = abs(cumulative[index] - cumulative[origin])
        arc = min(arc, total - arc)
        if arc > 0.060:
            far_move = max(
                far_move, (dense_after[index] - dense_before[index]).length
            )
    lines.append(
        f"  drag: drag_index={drag_index} far_index={far_index} "
        f"far_move(>60mm arc)={far_move*1000:.3f}mm wipe={wipe_deg:.1f}deg"
    )
    return far_move * 1000.0, wipe_deg


def _refine_deviation(lines):
    bpy.ops.rigo.auto_trimline()
    perimeter = _perimeter()
    dense_pre = curve_build_ops._curve_world_samples(perimeter)
    pre = len(perimeter.data.splines[0].bezier_points)
    bpy.ops.rigo.refine_trimline()
    perimeter = _perimeter()
    post = len(perimeter.data.splines[0].bezier_points)
    dense_post = curve_build_ops._curve_world_samples(perimeter)
    tree = KDTree(len(dense_pre))
    for index, point in enumerate(dense_pre):
        tree.insert(point, index)
    tree.balance()
    worst = max(tree.find(point)[2] for point in dense_post)
    lines.append(
        f"  refine {pre}->{post}: max shape deviation {worst*1000:.4f}mm"
    )
    return worst * 1000.0


def _visible_names():
    return sorted(
        obj.name
        for obj in bpy.context.view_layer.objects
        if obj is not None and not obj.hide_get()
    )


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = [f"enforced_level=P{ENFORCED_LEVEL}"]
    try:
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        depsgraph = bpy.context.evaluated_depsgraph_get()
        scan_bvh = BVHTree.FromObject(scan, depsgraph)
        perimeter = _perimeter()

        ratio, jump_p95, baseline = _junction_ratio(perimeter)
        lines.append(
            f"  junction ratio={ratio:.2f} (jump_p95={jump_p95:.1f} "
            f"baseline={baseline:.2f} 1/m)"
        )
        _gate(2, "junction_curvature_ratio<=3", ratio <= 3.0, f"{ratio:.2f}")

        gap_p95, gap_max = _displayed_vs_built(perimeter)
        lines.append(
            f"  displayed-vs-built gap p95={gap_p95*1000:.3f}mm "
            f"max={gap_max*1000:.3f}mm"
        )
        _gate(2, "displayed_vs_built_p95<=1mm", gap_p95 <= 0.001, f"{gap_p95*1000:.3f}")
        _gate(2, "displayed_vs_built_max<=2mm", gap_max <= 0.002, f"{gap_max*1000:.3f}")

        corner_error, chord = _opening_measurements(perimeter)
        lines.append(
            f"  opening corners: worst |theta| error={corner_error:.2f}deg; "
            f"waist chord={chord:.1f}mm (requested {settings.opening_width:.1f})"
        )
        _gate(2, "corner_theta_error<=1.5deg", corner_error <= 1.5, f"{corner_error:.2f}")
        _gate(
            2,
            "opening_chord_within_5mm",
            abs(chord - settings.opening_width) <= 5.0,
            f"{chord:.1f}",
        )

        gap = _min_non_adjacent_gap(
            curve_build_ops._curve_world_samples(perimeter)
        )
        lines.append(f"  min non-adjacent self-gap={gap*1000:.2f}mm")
        _gate(1, "no_self_crossing_gap>3mm", gap > 0.003, f"{gap*1000:.2f}")

        far_move, wipe = _drag_experiment(scan, scan_bvh, lines)
        _gate(3, "drag_influence>60mm<=0.5mm", far_move <= 0.5, f"{far_move:.3f}")
        _gate(3, "manual_handle_preserved<=0.5deg", wipe <= 0.5, f"{wipe:.1f}")

        refine_dev = _refine_deviation(lines)
        _gate(4, "refine_deviation<=0.01mm", refine_dev <= 0.01, f"{refine_dev:.4f}")

        # --- lifecycle + display authority -------------------------------- #
        bpy.ops.rigo.auto_trimline()
        first = sorted(o.name for o in bpy.data.objects if "Trim" in o.name)
        bpy.ops.rigo.auto_trimline()
        second = sorted(o.name for o in bpy.data.objects if "Trim" in o.name)
        _gate(1, "regen_trimline_no_duplicates", first == second, str(second))

        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result, error = {"CANCELLED"}, str(exc).strip()[:120]
        _gate(1, "generate_1_finished", result == {"FINISHED"}, error)
        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result, error = {"CANCELLED"}, str(exc).strip()[:120]
        _gate(1, "generate_2_finished", result == {"FINISHED"}, error)
        leftovers = sorted(
            o.name
            for o in bpy.data.objects
            if ".0" in o.name or "Candidate" in o.name or "Previous" in o.name
        )
        _gate(1, "no_stale_objects", not leftovers, str(leftovers))

        corset = bpy.data.objects.get("Rigo Corset")
        build = bpy.data.objects.get("Rigo Build Trim Perimeter")
        _gate(1, "corset_exists", corset is not None, "")
        _gate(
            1,
            "corset_clean",
            corset is not None
            and corset.get("rigo_generation_rim_intersections", 1) == 0
            and corset.get("rigo_generation_zero_area_faces", 1) == 0,
            "",
        )
        if corset is not None:
            import hashlib

            ordered = [
                tuple(round(c, 9) for c in v.co)
                for v in corset.data.vertices
            ]
            lines.append(
                f"  corset verts={len(corset.data.vertices)} hash="
                f"{hashlib.sha256(repr(ordered).encode()).hexdigest()[:16]}"
            )

        default_view = _visible_names()
        lines.append(f"  BRACE view default (overlay off): {default_view}")
        _gate(
            1,
            "overlay_off_single_authority",
            default_view == ["Rigo Corset"],
            str(default_view),
        )
        settings.show_trim_overlay = True
        overlay_on = _visible_names()
        lines.append(f"  BRACE view overlay ON: {overlay_on}")
        _gate(
            1,
            "brace_view_overlay_on",
            overlay_on == ["Rigo Build Trim Perimeter", "Rigo Corset"],
            str(overlay_on),
        )
        if build is not None and corset is not None:
            radius = build.data.bevel_depth
            centerline = _centerline(build)
            corset_bvh = BVHTree.FromObject(
                corset, bpy.context.evaluated_depsgraph_get()
            )
            inverse = corset.matrix_world.inverted()
            distances = sorted(
                (
                    (corset.matrix_world @ hit[0]) - point
                ).length
                for point in centerline
                for hit in (corset_bvh.find_nearest(inverse @ point),)
                if hit[0] is not None
            )
            lines.append(
                f"  overlay tube: r={radius*1000:.2f}mm clearance "
                f"min={distances[0]*1000:.3f} p50={_pct(distances, 0.5)*1000:.3f} "
                f"max={distances[-1]*1000:.3f}mm"
            )
            _gate(
                1,
                "overlay_clear_of_shell",
                distances[0] >= radius + 0.0005,
                f"min={distances[0]*1000:.3f} r={radius*1000:.2f}",
            )
            # Until P2 the preview copies the source curve, so it inherits the
            # displayed-vs-built lateral wander; deriving it from the cutter
            # path makes it hug the shell, which is when this gate turns on.
            _gate(
                2,
                "overlay_hugs_shell<=3.5mm",
                distances[-1] <= 0.0035,
                f"max={distances[-1]*1000:.3f}",
            )
        settings.show_trim_overlay = False
        overlay_off = _visible_names()
        lines.append(f"  BRACE view overlay back OFF: {overlay_off}")
        _gate(
            1,
            "overlay_toggle_returns_clean",
            overlay_off == ["Rigo Corset"],
            str(overlay_off),
        )
        from bl_ext.user_default.rigo_brace.operators import design_ops

        design_ops._set_design_view(bpy.context, "TRIM")
        trim_view = _visible_names()
        _gate(
            1,
            "trim_view_single_authority",
            trim_view == sorted([scan.name, "Rigo Trim Perimeter"]),
            str(trim_view),
        )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
        _gate(1, "no_exception", False, repr(error))

    enforced_fail = [
        (level, name, detail)
        for level, name, ok, detail in GATES
        if level <= ENFORCED_LEVEL and not ok
    ]
    lines.append("")
    for level, name, ok, detail in GATES:
        status = "PASS" if ok else (
            "FAIL" if level <= ENFORCED_LEVEL else "report-only"
        )
        lines.append(f"  [P{level}] {name}: {status} ({detail})")
    lines.append("")
    lines.append(f"PASS={not enforced_fail}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
