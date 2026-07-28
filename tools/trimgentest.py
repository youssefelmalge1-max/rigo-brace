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
ENFORCED_LEVEL = 4

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


def _displayed_vs_raw(perimeter):
    """Displayed line against its own control curve: the off-surface bulge.

    NOT the displayed-versus-built number. The build projects the raw curve
    onto the mold, which removes exactly this bulge, so a large value here does
    not mean the cut lands in the wrong place - see `_displayed_vs_built`.
    """
    dense = curve_build_ops._curve_world_samples(perimeter)
    displayed = _centerline(perimeter)
    tree = KDTree(len(dense))
    for index, point in enumerate(dense):
        tree.insert(point, index)
    tree.balance()
    gaps = sorted(tree.find(point)[2] for point in displayed)
    return _pct(gaps, 0.95), gaps[-1]


def _signed_body_distances(scan, points):
    """Signed distance to the body: negative means inside the patient."""
    bvh = BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())
    inverse = scan.matrix_world.inverted()
    normal_matrix = inverse.transposed().to_3x3()
    signed = []
    for point in points:
        hit = bvh.find_nearest(inverse @ point)
        if hit[0] is None:
            continue
        surface = scan.matrix_world @ hit[0]
        normal = (normal_matrix @ hit[1]).normalized()
        signed.append((point - surface).dot(normal))
    return sorted(signed)


def _preview_above_surface(scan, lines):
    """The editable preview must never be drawn inside the patient.

    Measured signed, because an unsigned distance cannot tell a 1.5 mm
    standoff from a 1.5 mm penetration - and before this fix those were
    exactly the two populations present.
    """
    bpy.ops.rigo.auto_trimline()
    perimeter = _perimeter()
    signed = _signed_body_distances(scan, _centerline(perimeter))
    inside = [value for value in signed if value < 0.0]
    lines.append(
        f"  preview vs body: n={len(signed)} signed_mm "
        f"min={signed[0]*1000:+.3f} p50={_pct(signed, 0.5)*1000:+.3f} "
        f"max={signed[-1]*1000:+.3f} | inside the body: {len(inside)}/"
        f"{len(signed)} ({100.0*len(inside)/max(len(signed),1):.1f}%)"
    )
    return len(inside), signed[0] * 1000.0


def _body_footprint(scan, points):
    """Where each sample sits ON the patient body - the common frame."""
    bvh = BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())
    inverse = scan.matrix_world.inverted()
    footprint = []
    for point in points:
        hit = bvh.find_nearest(inverse @ point)
        if hit[0] is not None:
            footprint.append(scan.matrix_world @ hit[0])
    return footprint


def _displayed_vs_built(perimeter, overlay, scan):
    """Did the cut land where the line was drawn, measured on the body.

    Decomposing the raw separation against an estimated normal is the wrong
    instrument here: the two curves are ~10 mm apart by design (liner + wall +
    display lift), so a 15-degree error in the normal estimate alone fabricates
    2.6 mm of "tangential" error - which is exactly what the first version of
    this gate reported.

    Both curves are therefore dropped onto the patient body first. Their
    footprints share one surface, so the distance between them is tangential by
    construction and carries no normal component to remove. Distance is taken
    to the footprint POLYLINE, not to its nearest sample, so ~1 mm sampling
    does not masquerade as up to 0.5 mm of deviation.
    """
    if overlay is None or scan is None:
        return None
    displayed = _body_footprint(scan, _centerline(perimeter))
    built = _body_footprint(scan, _centerline(overlay))
    if not displayed or not built:
        return None
    tree = KDTree(len(built))
    for index, point in enumerate(built):
        tree.insert(point, index)
    tree.balance()
    distances = sorted(
        curve_build_ops._distance_to_polyline_m(
            point, built, tree.find(point)[1]
        )
        for point in displayed
    )
    return _pct(distances, 0.95), distances[-1]


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


def _perform_drag(perimeter, scan, scan_bvh, drag_index, millimetres=8.0):
    """Drag a station by a distance along the surface tangent plane."""
    points = perimeter.data.splines[0].bezier_points
    drag_world = perimeter.matrix_world @ points[drag_index].co
    normal = _scan_normal_world(scan, scan_bvh, drag_world)
    direction = Vector((0.0, 0.0, 1.0))
    direction -= normal * direction.dot(normal)
    direction.normalize()
    _perform_drag_to(
        perimeter,
        scan,
        scan_bvh,
        drag_index,
        drag_world + direction * (millimetres * 0.001),
    )
    return drag_world


def _perform_drag_to(perimeter, scan, scan_bvh, drag_index, target_world):
    """Replicate RIGO_OT_slide_trimline_on_surface._move_dragged_point.

    Mirrors the operator's arc-length band, protected-feature policy and
    banded solve. Visibility is the one thing left out - it depends on a live
    viewport - so every station in the band is treated as visible, which is
    the harder case for the locality gates.
    """
    settings = bpy.context.scene.rigo_brace
    spline = perimeter.data.splines[0]
    points = spline.bezier_points
    matrix = perimeter.matrix_world
    inverse_matrix = matrix.inverted()
    count = len(points)
    start = [p.co.copy() for p in points]

    radius_m = settings.trim_edit_radius * 0.001
    weights = trimline_ops.edit_weights(points, drag_index, radius_m)
    run = trimline_ops._cyclic_run(weights, drag_index, count)
    band = (
        [(run[0] - 1) % count] + run + [(run[-1] + 1) % count]
        if len(run) + 2 <= count
        else list(range(count))
    )
    protected = (
        trimline_ops._opening_locked_indices(
            perimeter, [matrix @ point.co for point in points]
        )
        if settings.trim_edit_lock_features
        else set()
    )

    delta = (inverse_matrix @ target_world) - start[drag_index]

    for index, weight in weights.items():
        if index != drag_index and index in protected:
            continue
        intended = start[index] + delta * weight
        fitted = trimline_ops._nearest_surface_world(
            scan, scan_bvh, matrix @ intended
        )
        if fitted is not None:
            points[index].co = inverse_matrix @ fitted
    trimline_ops.solve_band_c2(
        spline, band, manual=trimline_ops.manual_handle_indices(perimeter)
    )
    perimeter["rigo_trim_handle_model"] = "C2_BANDED"
    trimline_ops.mark_handles_solved(perimeter)
    perimeter.data.update_tag()


def _back_index(perimeter):
    matrix = perimeter.matrix_world
    points = perimeter.data.splines[0].bezier_points
    return min(
        range(len(points)),
        key=lambda i: abs(abs(_theta_deg(perimeter, matrix @ points[i].co)) - 180.0),
    )


def _side_index(perimeter):
    matrix = perimeter.matrix_world
    points = perimeter.data.splines[0].bezier_points
    return min(
        range(len(points)),
        key=lambda i: abs(_theta_deg(perimeter, matrix @ points[i].co) - 90.0),
    )


def _influence_profile(before, after, drag_world):
    """Max displacement by arc distance from the drag, in millimetres."""
    cumulative = [0.0]
    for index in range(1, len(before)):
        cumulative.append(
            cumulative[-1] + (before[index] - before[index - 1]).length
        )
    total = cumulative[-1]
    origin = min(
        range(len(before)), key=lambda i: (before[i] - drag_world).length
    )
    bands = [
        (0.0, 0.010), (0.010, 0.025), (0.025, 0.040), (0.040, 0.060),
        (0.060, 0.080), (0.080, 0.120), (0.120, 10.0),
    ]
    profile = {band: 0.0 for band in bands}
    for index in range(len(before)):
        arc = abs(cumulative[index] - cumulative[origin])
        arc = min(arc, total - arc)
        displacement = (after[index] - before[index]).length
        for band in bands:
            if band[0] <= arc < band[1]:
                profile[band] = max(profile[band], displacement)
    return profile


def _band_arc_extent(perimeter, drag_index):
    """Arc distance from the drag to the outer edge of the solved band.

    The architectural guarantee is not "nothing moves past N mm" - it is
    "nothing moves outside the solved band". The band is the influence radius
    plus one clamp station either side, and station spacing on this fixture
    runs to 132 mm, so a fixed 60 mm threshold would be asserting something
    the design never claimed. Measuring the band's own extent gates the real
    contract instead.
    """
    points = perimeter.data.splines[0].bezier_points
    count = len(points)
    radius_m = bpy.context.scene.rigo_brace.trim_edit_radius * 0.001
    weights = trimline_ops.edit_weights(points, drag_index, radius_m)
    run = trimline_ops._cyclic_run(weights, drag_index, count)
    band = (
        [(run[0] - 1) % count] + run + [(run[-1] + 1) % count]
        if len(run) + 2 <= count
        else list(range(count))
    )
    distances = trimline_ops._cyclic_arc_distances(
        [point.co.copy() for point in points], drag_index
    )
    return max(distances[index] for index in band), band


def _drag_locality(scan, scan_bvh, lines, drag_index=None, label="drag"):
    """How far a drag reaches, with no handle edit to confound it."""
    bpy.ops.rigo.auto_trimline()
    perimeter = _perimeter()
    if drag_index is None:
        drag_index = _back_index(perimeter)
    band_extent, band = _band_arc_extent(perimeter, drag_index)
    before = curve_build_ops._curve_world_samples(perimeter)
    drag_world = _perform_drag(perimeter, scan, scan_bvh, drag_index)
    after = curve_build_ops._curve_world_samples(perimeter)
    profile = _influence_profile(before, after, drag_world)
    lines.append(
        f"  {label} influence profile (8mm drag at control {drag_index}; "
        f"solved band = {len(band)} stations reaching {band_extent*1000:.1f}mm "
        f"of arc):"
    )
    for (low, high), value in profile.items():
        lines.append(
            f"    {low*1000:.0f}-{high*1000:.0f}mm arc: {value*1000:.4f}mm"
        )
    # Beyond the band nothing may move at all.
    cumulative = [0.0]
    for index in range(1, len(before)):
        cumulative.append(
            cumulative[-1] + (before[index] - before[index - 1]).length
        )
    total = cumulative[-1]
    origin = min(
        range(len(before)), key=lambda i: (before[i] - drag_world).length
    )
    beyond_band = 0.0
    for index in range(len(before)):
        arc = abs(cumulative[index] - cumulative[origin])
        arc = min(arc, total - arc)
        if arc > band_extent * 1.02:
            beyond_band = max(
                beyond_band, (after[index] - before[index]).length
            )
    lines.append(
        f"    beyond the solved band ({band_extent*1000:.1f}mm): "
        f"{beyond_band*1000:.6f}mm"
    )
    far = max(
        value for (low, _high), value in profile.items() if low >= 0.060
    )
    return far * 1000.0, beyond_band * 1000.0


def _exact_outside_band(scan, scan_bvh, lines):
    """Outside the influenced arc, nothing may change - not one bit."""
    bpy.ops.rigo.auto_trimline()
    perimeter = _perimeter()
    points = perimeter.data.splines[0].bezier_points
    count = len(points)
    drag_index = _back_index(perimeter)
    radius_m = bpy.context.scene.rigo_brace.trim_edit_radius * 0.001
    weights = trimline_ops.edit_weights(points, drag_index, radius_m)
    band = set(trimline_ops._cyclic_run(weights, drag_index, count))
    band.update({(min(band) - 1) % count, (max(band) + 1) % count})
    outside = [index for index in range(count) if index not in band]
    snapshot = {
        index: (
            points[index].co.copy(),
            points[index].handle_left.copy(),
            points[index].handle_right.copy(),
            points[index].handle_left_type,
            points[index].handle_right_type,
        )
        for index in outside
    }
    _perform_drag(perimeter, scan, scan_bvh, drag_index)
    points = _perimeter().data.splines[0].bezier_points
    worst_co = worst_handle = 0.0
    type_changes = 0
    for index, state in snapshot.items():
        worst_co = max(worst_co, (points[index].co - state[0]).length)
        worst_handle = max(
            worst_handle,
            (points[index].handle_left - state[1]).length,
            (points[index].handle_right - state[2]).length,
        )
        if (
            points[index].handle_left_type != state[3]
            or points[index].handle_right_type != state[4]
        ):
            type_changes += 1
    lines.append(
        f"  outside-band exactness ({len(outside)} of {count} stations): "
        f"max control move={worst_co*1e9:.3f}nm max handle move="
        f"{worst_handle*1e9:.3f}nm handle-type changes={type_changes}"
    )
    return worst_co, worst_handle, type_changes


def _seam_wrap_locality(scan, scan_bvh, lines):
    """An edit at the cyclic seam must behave like an edit anywhere else.

    Station 0 is where the index wraps. If the falloff were computed on index
    ranges instead of cyclic arc length, the influence would stop dead at the
    seam and only the ascending side would move.

    Two fixture details matter. Feature protection is switched OFF here
    because on this template the opening - and therefore the protected
    stations - sits exactly on the seam, so the two policies would otherwise
    be measured together and neither conclusively. And the radius is widened
    past the local station spacing, since a radius narrower than the gap to
    the next station would leave both neighbours unmoved and the test would
    pass vacuously.
    """
    settings = bpy.context.scene.rigo_brace
    original_radius = settings.trim_edit_radius
    original_lock = settings.trim_edit_lock_features
    try:
        settings.trim_edit_lock_features = False
        settings.trim_edit_radius = 120.0
        bpy.ops.rigo.auto_trimline()
        perimeter = _perimeter()
        points = perimeter.data.splines[0].bezier_points
        count = len(points)
        original = [point.co.copy() for point in points]
        band_extent, _band = _band_arc_extent(perimeter, 0)
        before = curve_build_ops._curve_world_samples(perimeter)
        drag_world = _perform_drag(perimeter, scan, scan_bvh, 0)
        after = curve_build_ops._curve_world_samples(perimeter)
        points = _perimeter().data.splines[0].bezier_points
        ascending = (points[1].co - original[1]).length * 1000.0
        descending = (points[count - 1].co - original[count - 1]).length * 1000.0
        # Equal movement would actually be WRONG: falloff is by arc length, and
        # these two stations sit at different arc distances from station 0
        # (spacing runs 24-132 mm on this fixture). What must hold across the
        # seam is the falloff LAW - each neighbour moves in proportion to
        # cos-falloff of its own measured arc distance, whichever side of the
        # index wrap it is on.
        distances = trimline_ops._cyclic_arc_distances(original, 0)
        radius_m = settings.trim_edit_radius * 0.001

        def _expected(distance):
            if distance >= radius_m:
                return 0.0
            return 0.5 * (1.0 + math.cos(math.pi * distance / radius_m))

        expected_ratio = _expected(distances[count - 1]) / max(
            _expected(distances[1]), 1e-9
        )
        measured_ratio = descending / max(ascending, 1e-9)
        balance = abs(measured_ratio - expected_ratio) / max(expected_ratio, 1e-9)
        profile = _influence_profile(before, after, drag_world)
        far = max(value for (low, _h), value in profile.items() if low >= 0.120)
    finally:
        settings.trim_edit_radius = original_radius
        settings.trim_edit_lock_features = original_lock
    lines.append(
        f"  seam wrap (120mm radius, protection off, drag at station 0): "
        f"station 1 moved {ascending:.3f}mm at "
        f"{distances[1]*1000:.1f}mm arc, station {count-1} moved "
        f"{descending:.3f}mm at {distances[count-1]*1000:.1f}mm arc; "
        f"falloff-law error={balance:.3f}, band={band_extent*1000:.1f}mm, "
        f"beyond120mm={far*1000:.4f}mm"
    )
    return ascending, descending, balance


def _protected_features(scan, scan_bvh, lines):
    """A protected station must not drift when an edit lands nearby.

    Policy under test: protected stations move ONLY when dragged directly.
    An edit elsewhere whose influence radius covers them leaves them exactly
    where they were.
    """
    bpy.ops.rigo.auto_trimline()
    perimeter = _perimeter()
    points = perimeter.data.splines[0].bezier_points
    count = len(points)
    matrix = perimeter.matrix_world
    protected = sorted(
        trimline_ops._opening_locked_indices(
            perimeter, [matrix @ point.co for point in points]
        )
    )
    if not protected:
        lines.append("  protected features: NONE FOUND (fixture problem)")
        return None, None
    # Drag the station two along from a protected one, so the protected
    # station sits well inside the influence radius.
    target = protected[0]
    drag_index = (target + 2) % count
    original = [point.co.copy() for point in points]
    _perform_drag(perimeter, scan, scan_bvh, drag_index)
    points = _perimeter().data.splines[0].bezier_points
    drift = max(
        (points[index].co - original[index]).length for index in protected
    ) * 1000.0
    neighbour_moved = (
        points[drag_index].co - original[drag_index]
    ).length * 1000.0
    lines.append(
        f"  protected features: {len(protected)} stations {protected}; "
        f"drag at {drag_index} moved it {neighbour_moved:.3f}mm, "
        f"max protected drift={drift:.6f}mm"
    )
    return drift, neighbour_moved


def _reversibility(scan, scan_bvh, lines):
    """An edit and its exact inverse must return the original shape.

    The inverse of "drag this station to there" is "drag it back to where it
    was" - NOT "drag it 8 mm the other way". The second is what the first
    version of this test did, and it can't return: the direction is rebuilt
    from the moved point's surface normal, and each drag re-projects onto a
    curved surface, so -8 mm from the new position lands somewhere else
    entirely. That measured 0.396 mm of "irreversibility" which was purely
    the test's own construction.
    """
    bpy.ops.rigo.auto_trimline()
    perimeter = _perimeter()
    drag_index = _back_index(perimeter)
    points = perimeter.data.splines[0].bezier_points
    before_states = [
        (p.co.copy(), p.handle_left.copy(), p.handle_right.copy()) for p in points
    ]
    before_shape = curve_build_ops._curve_world_samples(perimeter)
    home_world = perimeter.matrix_world @ points[drag_index].co
    _perform_drag(perimeter, scan, scan_bvh, drag_index, millimetres=8.0)
    _perform_drag_to(perimeter, scan, scan_bvh, drag_index, home_world)
    points = _perimeter().data.splines[0].bezier_points
    after_shape = curve_build_ops._curve_world_samples(perimeter)
    control_drift = max(
        (point.co - state[0]).length for point, state in zip(points, before_states)
    ) * 1000.0
    handle_drift = max(
        max(
            (point.handle_left - state[1]).length,
            (point.handle_right - state[2]).length,
        )
        for point, state in zip(points, before_states)
    ) * 1000.0
    shape_drift = max(
        (a - b).length for a, b in zip(after_shape, before_shape)
    ) * 1000.0
    lines.append(
        f"  reversibility (+8mm then -8mm): control drift={control_drift:.4f}mm "
        f"handle drift={handle_drift:.4f}mm evaluated-shape drift="
        f"{shape_drift:.4f}mm"
    )
    return control_drift, handle_drift, shape_drift


def _undo_exactness(scan, scan_bvh, lines):
    """The real reversibility guarantee: Ctrl+Z restores the exact state.

    Uses the operator's own snapshot/restore pair, so this measures the code
    path the orthotist actually triggers rather than a re-implementation.
    """
    bpy.ops.rigo.auto_trimline()
    perimeter = _perimeter()
    points = perimeter.data.splines[0].bezier_points
    snapshot = trimline_ops._capture_point_states(points)
    before_shape = curve_build_ops._curve_world_samples(perimeter)
    _perform_drag(perimeter, scan, scan_bvh, _back_index(perimeter))
    trimline_ops._restore_point_states(points, snapshot)
    trimline_ops.mark_handles_solved(perimeter)
    perimeter.data.update_tag()
    after_shape = curve_build_ops._curve_world_samples(_perimeter())
    control = max(
        (point.co - state[0]).length for point, state in zip(points, snapshot)
    ) * 1000.0
    handle = max(
        max(
            (point.handle_left - state[1]).length,
            (point.handle_right - state[2]).length,
        )
        for point, state in zip(points, snapshot)
    ) * 1000.0
    shape = max(
        (a - b).length for a, b in zip(after_shape, before_shape)
    ) * 1000.0
    lines.append(
        f"  undo exactness: control={control:.3e}mm handle={handle:.3e}mm "
        f"evaluated-shape={shape:.3e}mm"
    )
    return control, handle, shape


def _repeat_edit_buildability(scan, scan_bvh, lines):
    """After a sequence of ordinary edits the brace must still build."""
    bpy.ops.rigo.auto_trimline()
    perimeter = _perimeter()
    count = len(perimeter.data.splines[0].bezier_points)
    for step in range(4):
        _perform_drag(
            perimeter,
            scan,
            scan_bvh,
            (_back_index(perimeter) + step * 3) % count,
            millimetres=5.0,
        )
    stale = trimline_ops.handles_are_stale(perimeter)
    try:
        result = bpy.ops.rigo.generate_curve_corset()
        error = ""
    except RuntimeError as exc:
        result, error = {"CANCELLED"}, str(exc).strip()[:120]
    corset = bpy.data.objects.get("Rigo Corset")
    lines.append(
        f"  repeat-edit buildability: 4 drags -> stale={stale} "
        f"generate={result} {error}"
    )
    return result == {"FINISHED"} and corset is not None and not stale


def _handle_preservation(scan, scan_bvh, lines):
    """Does an unrelated drag overwrite a hand-set handle elsewhere?"""
    bpy.ops.rigo.auto_trimline()
    perimeter = _perimeter()
    points = perimeter.data.splines[0].bezier_points
    far_index = _side_index(perimeter)
    drag_index = _back_index(perimeter)
    far_point = points[far_index]
    normal = _scan_normal_world(
        scan, scan_bvh, perimeter.matrix_world @ far_point.co
    )
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
    trimline_ops.add_manual_handle(perimeter, far_index)
    requested = (far_point.handle_right - far_point.co).normalized()
    _perform_drag(perimeter, scan, scan_bvh, drag_index)
    delivered = (far_point.handle_right - far_point.co).normalized()
    wipe = math.degrees(requested.angle(delivered))
    lines.append(
        f"  handle preservation: control {far_index} hand-rotated 20deg, "
        f"then control {drag_index} dragged; hand-set direction lost "
        f"{wipe:.1f}deg"
    )
    return wipe


def _refine_deviation(lines):
    """Adding editing capacity must not move the clinical line at all.

    Exact De Casteljau subdivision is shape-preserving by construction, so the
    deviation should be numerical noise rather than a tolerance to negotiate.
    Measured both ways: the evaluated curve against its pre-refine self, and
    the ORIGINAL control points, which must not have moved by so much as a
    nanometre.
    """
    bpy.ops.rigo.auto_trimline()
    perimeter = _perimeter()
    dense_pre = curve_build_ops._curve_world_samples(perimeter)
    originals = [
        point.co.copy() for point in perimeter.data.splines[0].bezier_points
    ]
    pre = len(originals)
    bpy.ops.rigo.refine_trimline()
    perimeter = _perimeter()
    points = perimeter.data.splines[0].bezier_points
    post = len(points)
    dense_post = curve_build_ops._curve_world_samples(perimeter)
    tree = KDTree(len(dense_pre))
    for index, point in enumerate(dense_pre):
        tree.insert(point, index)
    tree.balance()
    worst = max(tree.find(point)[2] for point in dense_post)
    # Exact subdivision interleaves: original stations land on even indices.
    original_move = max(
        (points[index * 2].co - original).length
        for index, original in enumerate(originals)
    ) if post == pre * 2 else math.inf
    lines.append(
        f"  refine {pre}->{post}: max shape deviation {worst*1000:.6f}mm; "
        f"original stations moved {original_move*1000:.3e}mm"
    )
    return worst * 1000.0, original_move * 1000.0, (pre, post)


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

        raw_p95, raw_max = _displayed_vs_raw(perimeter)
        lines.append(
            f"  displayed-vs-raw-control-curve (off-surface bulge, removed by "
            f"projection) p95={raw_p95*1000:.3f}mm max={raw_max*1000:.3f}mm"
        )

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

        # Prove the self-approach fallback actually engages. It never fires on
        # the reference brace (13.7 mm clearance against a 6 mm trigger), and
        # safety code that no test exercises is not safety code. Raising the
        # trigger above the measured clearance must send the curve back to the
        # old tangent-continuous rule - which shows up as the junction ratio
        # returning to its pre-P2 value.
        original_gap = trimline_ops.C2_MIN_SELF_GAP_M
        try:
            trimline_ops.C2_MIN_SELF_GAP_M = 0.050
            bpy.ops.rigo.auto_trimline()
            fallback_ratio = _junction_ratio(_perimeter())[0]
            fallback_model = str(
                _perimeter().get("rigo_trim_handle_model", "?")
            )
        finally:
            trimline_ops.C2_MIN_SELF_GAP_M = original_gap
        lines.append(
            f"  self-approach fallback (trigger raised to 50mm): "
            f"junction ratio={fallback_ratio:.2f} model={fallback_model}"
        )
        _gate(
            2,
            "self_approach_fallback_engages",
            fallback_ratio > 5.0,
            f"{fallback_ratio:.2f}",
        )
        _gate(
            2,
            "fallback_is_stamped_honestly",
            fallback_model == "C2_SELF_APPROACH_FALLBACK",
            fallback_model,
        )
        bpy.ops.rigo.auto_trimline()

        preview_inside, preview_min = _preview_above_surface(scan, lines)
        _gate(
            1,
            "preview_never_inside_body",
            preview_inside == 0,
            f"{preview_inside} samples, min {preview_min:+.3f}mm",
        )

        far_move, beyond_band = _drag_locality(scan, scan_bvh, lines)
        _gate(
            3,
            "nothing_moves_outside_solved_band",
            beyond_band <= 0.001,
            f"{beyond_band:.6f}",
        )
        wipe = _handle_preservation(scan, scan_bvh, lines)
        _gate(3, "manual_handle_preserved<=0.5deg", wipe <= 0.5, f"{wipe:.1f}")

        worst_co, worst_handle, type_changes = _exact_outside_band(
            scan, scan_bvh, lines
        )
        _gate(
            3, "outside_band_controls_exact", worst_co == 0.0, f"{worst_co:.3e}"
        )
        _gate(
            3,
            "outside_band_handles_exact",
            worst_handle == 0.0,
            f"{worst_handle:.3e}",
        )
        _gate(
            3, "outside_band_handle_types_exact", type_changes == 0, f"{type_changes}"
        )

        ascending, descending, balance = _seam_wrap_locality(
            scan, scan_bvh, lines
        )
        _gate(3, "seam_both_sides_move", min(ascending, descending) > 0.1,
              f"{ascending:.3f}/{descending:.3f}")
        _gate(3, "seam_obeys_arclength_falloff_law<=0.15", balance <= 0.15,
              f"{balance:.3f}")

        drift, neighbour_moved = _protected_features(scan, scan_bvh, lines)
        if drift is not None:
            _gate(3, "protected_no_drift<=0.001mm", drift <= 0.001, f"{drift:.6f}")
            # Guards the fixture: if the drag itself did nothing, a zero drift
            # would prove nothing at all.
            _gate(3, "protected_fixture_actually_edits", neighbour_moved > 1.0,
                  f"{neighbour_moved:.3f}")

        control_drift, handle_drift, shape_drift = _reversibility(
            scan, scan_bvh, lines
        )
        # Dragging out and back is NOT an undo, and cannot be bit-exact: each
        # drag re-projects onto a curved surface, and going out and back along
        # a tangent plane leaves a residual of about d^2/2R - for d=8mm on a
        # ~100mm radius torso that predicts ~0.32mm, against 0.39mm measured.
        # The gates bound that residual; exactness is gated separately on the
        # actual undo path below.
        _gate(3, "dragback_controls<=0.5mm", control_drift <= 0.5,
              f"{control_drift:.4f}")
        _gate(3, "dragback_handles<=3mm", handle_drift <= 3.0,
              f"{handle_drift:.4f}")
        _gate(3, "dragback_shape<=1.5mm", shape_drift <= 1.5,
              f"{shape_drift:.4f}")

        undo_control, undo_handle, undo_shape = _undo_exactness(
            scan, scan_bvh, lines
        )
        _gate(3, "undo_controls_exact", undo_control == 0.0, f"{undo_control:.3e}")
        _gate(3, "undo_handles_exact", undo_handle == 0.0, f"{undo_handle:.3e}")
        _gate(3, "undo_shape_exact", undo_shape == 0.0, f"{undo_shape:.3e}")

        _gate(
            3,
            "repeat_edits_still_build",
            _repeat_edit_buildability(scan, scan_bvh, lines),
            "",
        )

        refine_dev, refine_original_move, refine_counts = _refine_deviation(lines)
        _gate(4, "refine_deviation<=0.01mm", refine_dev <= 0.01, f"{refine_dev:.4f}")
        _gate(
            4,
            "refine_originals_unmoved",
            refine_original_move <= 1.0e-9,
            f"{refine_original_move:.3e}",
        )
        _gate(
            4,
            "refine_doubles_capacity",
            refine_counts[1] == refine_counts[0] * 2,
            f"{refine_counts[0]}->{refine_counts[1]}",
        )

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
        # Contract change (owner, 2026-07-28): only ONE authoritative boundary
        # may be drawn. The build overlay is a DERIVED path lifted clear of the
        # wall, so alongside the shell - whose edge already is the trimline -
        # it reads as a second, visibly separate boundary. It is now diagnostic
        # and needs the explicit non-clinical opt-in, so the overlay toggle
        # alone must change nothing.
        settings.show_trim_overlay = True
        clinical = _visible_names()
        lines.append(f"  BRACE view overlay toggled, diagnostics OFF: {clinical}")
        _gate(
            1,
            "overlay_toggle_alone_draws_nothing",
            clinical == ["Rigo Corset"],
            str(clinical),
        )
        settings.diagnostic_overlays = True
        overlay_on = _visible_names()
        lines.append(f"  BRACE view overlay ON (diagnostics engaged): {overlay_on}")
        _gate(
            1,
            "brace_view_overlay_on_under_diagnostics",
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
        built = _displayed_vs_built(_perimeter(), build, scan)
        if built is not None:
            lines.append(
                f"  DISPLAYED vs BUILT on the body: p95={built[0]*1000:.3f}mm "
                f"max={built[1]*1000:.3f}mm"
            )
            _gate(
                2,
                "displayed_vs_built_on_body_p95<=1mm",
                built[0] <= 0.001,
                f"{built[0]*1000:.3f}",
            )
            _gate(
                2,
                "displayed_vs_built_on_body_max<=2mm",
                built[1] <= 0.002,
                f"{built[1]*1000:.3f}",
            )
        settings.diagnostic_overlays = False
        withdrawn = _visible_names()
        lines.append(f"  diagnostic opt-in withdrawn: {withdrawn}")
        _gate(
            1,
            "withdrawing_diagnostics_returns_clean",
            withdrawn == ["Rigo Corset"],
            str(withdrawn),
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
