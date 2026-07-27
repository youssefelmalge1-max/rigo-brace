"""Auto trim lines by Rigo type — landmark-anchored template drape (DEC-0023).

The orthotist places the anatomical landmarks, picks a trim profile, and one
button creates one continuous perimeter containing the upper edge, lower edge,
and both opening sides. Edit on Body raycasts every drag onto the corrected
scan; a live Shrinkwrap keeps the evaluated line surface-bound.

Anchoring (all from placed landmarks, template z is normalized to the same
anchors on the reference mold):
- bottom  = mean z of TROCHANTER_L/R    (fallback: ILIAC_L/R, else scan base)
- waist   = z of WAISTLINE              (fallback: min-width level)
- top     = mean z of ACROMION_L/R      (fallback: AXILLA_L/R, else scan top)
- axis    = vertical line through the pelvis landmarks' XY centroid
- front   = from the axis toward the ASIS_L/R midpoint (fallback: -Y)

The exact parameterization is stamped onto the perimeter so Generate reuses it.
Every generated line requires orthotist review (template metadata).
"""

import math
from dataclasses import dataclass

import bpy
import gpu
from bpy.types import Operator
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import interpolate_bezier

from ..core import LANDMARK_PREFIX, mark_brace_dirty
from ..core import trim_templates

TRIM_TOP_NAME = "Rigo Trim Top"
TRIM_BOT_NAME = "Rigo Trim Bottom"
TRIM_PERIM_NAME = "Rigo Trim Perimeter"
SURFACE_OFFSET = 0.0015
TRIM_BRUSH_ITERATIONS = 12
# Gauss-Seidel sweeps for the periodic C2 tangent system. The matrix is
# strictly diagonally dominant by a factor of two, so error falls by ~2x per
# sweep; 200 is far past convergence for any clinical control count and still
# costs under a millisecond.
C2_SOLVE_PASSES = 200
# Knot spacing is chord length. Centripetal spacing (chord ** 0.5) is the
# textbook remedy when an interpolating spline overshoots on uneven data, and
# it does improve the curve itself - junction ratio 0.43 and self-clearance
# 16.5 mm at exponent 0.7. It was still rejected: at both 0.7 and 0.5 the
# REFERENCE brace stopped building ("2 local rim overlaps"). Every variant
# tried that reshapes the trimline more than plain chord-length C2 - two
# handle clamps, two station-refinement tolerances, two centripetal exponents
# - broke the build, which says the rim/offset stage has a narrow stability
# envelope rather than that the spline was wrong. Do not re-tune this without
# re-running rimresampletest and curvebuildtest.
# Clearance the Exact cutter needs between two stretches of trimline that are
# far apart ALONG the curve. The cutter ribbon is extruded +/- 1.5 mm along the
# surface normal, so two stretches closer than 3.0 mm merge it into a
# self-touching surface and the cut comes back non-manifold. 6 mm is that floor
# with a factor of two in hand.
C2_MIN_SELF_GAP_M = 0.006
# Samples per segment used for the self-approach check. Enough to catch a loop
# in a crowded segment without making the O(n^2) sweep expensive.
C2_GUARD_SAMPLES_PER_SEGMENT = 8
C2_GUARD_SAMPLE_BUDGET = 400


@dataclass(frozen=True)
class _TrimBrushConfig:
    center_index: int
    radius_m: float
    strength: float
    visible_indices: frozenset
    lock_opening: bool


@dataclass(frozen=True)
class _TrimBrushOutcome:
    affected: int
    maximum_movement_mm: float


@dataclass(frozen=True)
class _TrimBrushState:
    affected: frozenset
    distances: tuple
    config: _TrimBrushConfig


@dataclass(frozen=True)
class _SurfaceRayContext:
    region: object
    region_3d: object
    scan: object
    bvh: object


@dataclass(frozen=True)
class _RadialFitContext:
    axis: tuple
    front: tuple
    scan_matrix: object
    scan_inverse: object
    inverse_3: object
    normal_matrix: object
    bvh: object
    reach: float


def _scan_of(context):
    settings = context.scene.rigo_brace
    obj = settings.scan_object or context.active_object
    if obj is None or obj.type != "MESH":
        return None
    return obj


def _lm(name):
    obj = bpy.data.objects.get(f"{LANDMARK_PREFIX}{name}")
    return obj.location.copy() if obj is not None else None


def _mean_z(*names):
    zs = [p.z for p in (_lm(n) for n in names) if p is not None]
    return sum(zs) / len(zs) if zs else None


def _scan_extents(scan):
    cs = [scan.matrix_world @ Vector(c) for c in scan.bound_box]
    zmin = min(c.z for c in cs)
    zmax = max(c.z for c in cs)
    return zmin, zmax


def _anchors(context, scan):
    """(z_bottom, z_waist, z_top, axis_xy, front_dir, warnings)."""
    warnings = []
    zmin, zmax = _scan_extents(scan)

    z_bottom = _mean_z("TROCHANTER_L", "TROCHANTER_R")
    if z_bottom is None:
        z_bottom = _mean_z("ILIAC_L", "ILIAC_R")
        if z_bottom is not None:
            warnings.append("bottom anchored to iliac crests (no trochanters)")
    if z_bottom is None:
        z_bottom = zmin + 0.02 * (zmax - zmin)
        warnings.append("bottom estimated from the scan base — place trochanters")

    waist = _lm("WAISTLINE")
    z_waist = waist.z if waist is not None else None
    if z_waist is None:
        z_waist = zmin + 0.45 * (zmax - zmin)
        warnings.append("waist estimated — place the WAISTLINE landmark")

    z_top = _mean_z("ACROMION_L", "ACROMION_R")
    if z_top is None:
        z_top = _mean_z("AXILLA_L", "AXILLA_R")
        if z_top is not None:
            warnings.append("top anchored to axillae (no acromions)")
    if z_top is None:
        z_top = zmax - 0.02 * (zmax - zmin)
        warnings.append("top estimated from the scan top — place acromions")

    pelvis_pts = [
        p for p in (
            _lm("ASIS_L"), _lm("ASIS_R"), _lm("PSIS_L"), _lm("PSIS_R"),
            _lm("ILIAC_L"), _lm("ILIAC_R"),
        ) if p is not None
    ]
    if pelvis_pts:
        axis = Vector((
            sum(p.x for p in pelvis_pts) / len(pelvis_pts),
            sum(p.y for p in pelvis_pts) / len(pelvis_pts),
        ))
    else:
        cs = [scan.matrix_world @ Vector(c) for c in scan.bound_box]
        axis = Vector((
            (min(c.x for c in cs) + max(c.x for c in cs)) * 0.5,
            (min(c.y for c in cs) + max(c.y for c in cs)) * 0.5,
        ))
        warnings.append("axis estimated from the scan box — place pelvis landmarks")

    asis_l, asis_r = _lm("ASIS_L"), _lm("ASIS_R")
    if asis_l is not None and asis_r is not None:
        mid = (asis_l + asis_r) * 0.5
        front = Vector((mid.x - axis.x, mid.y - axis.y))
        if front.length > 1e-6:
            front.normalize()
        else:
            front = Vector((0.0, -1.0))
    else:
        front = Vector((0.0, -1.0))
        warnings.append("front assumed -Y — place ASIS L/R for exact orientation")

    return z_bottom, z_waist, z_top, axis, front, warnings


def _make_trim_curve(context, name, points, color):
    old = bpy.data.objects.get(name)
    if old is not None:
        data = old.data
        bpy.data.objects.remove(old, do_unlink=True)
        if data.users == 0:
            bpy.data.curves.remove(data)

    curve = bpy.data.curves.new(name, type="CURVE")
    curve.dimensions = "3D"
    # A thin inspection line: its centre is 1.5 mm above the body and the
    # radius stays below that offset, so the preview tube cannot enter the scan.
    curve.bevel_depth = 0.0012
    curve.bevel_resolution = 4
    curve.resolution_u = 24
    curve.render_resolution_u = 32
    spline = curve.splines.new("BEZIER")
    spline.use_cyclic_u = True
    spline.bezier_points.add(len(points) - 1)
    for bp, co in zip(spline.bezier_points, points):
        bp.co = co
        bp.handle_left_type = "AUTO"
        bp.handle_right_type = "AUTO"
    _set_c2_tangent_handles(spline)
    obj = bpy.data.objects.new(name, curve)
    obj.color = color
    obj.show_in_front = True
    context.scene.collection.objects.link(obj)
    return obj


def _set_linked_tangent_handle(points, index):
    """Set one conservative G1-continuous handle pair at a cyclic fit point."""
    point = points[index]
    previous = points[(index - 1) % len(points)].co
    current = point.co
    following = points[(index + 1) % len(points)].co
    tangent = following - previous
    if tangent.length_squared <= 1.0e-20:
        tangent = following - current
    if tangent.length_squared <= 1.0e-20:
        return
    tangent.normalize()
    reach = 0.25 * min(
        (current - previous).length,
        (following - current).length,
    )
    point.handle_left_type = "FREE"
    point.handle_right_type = "FREE"
    point.handle_left = current - tangent * reach
    point.handle_right = current + tangent * reach


def _set_clamped_tangent_handles(spline):
    """Create explicit, tangent-continuous handles with bounded reach."""
    points = spline.bezier_points
    if len(points) < 3:
        return
    for index in range(len(points)):
        _set_linked_tangent_handle(points, index)


def _periodic_c2_tangents(coordinates, passes=C2_SOLVE_PASSES):
    """Tangents making the closed interpolating cubic spline C2.

    Any tangent taken from a point's own neighbours is C1 at best: the
    curvature arriving at a control point is fixed by the segment on its left
    and the curvature leaving it by the segment on its right, and no local rule
    couples the two. Measured on the reference brace, chord-length Bessel
    tangents left the junction-curvature jump at 9.91x the within-segment
    baseline, against 9.70x for the previous 0.25 x min-chord rule - no
    improvement, because the defect is structural rather than a bad constant.

    Matching the second derivative across every join instead gives the standard
    non-uniform periodic system

        h_i m_(i-1) + 2(h_(i-1)+h_i) m_i + h_(i-1) m_(i+1) = 3(...)

    whose matrix is strictly diagonally dominant by a factor of two, so
    Gauss-Seidel converges geometrically and needs no cyclic-tridiagonal
    solver. The result drops the same measured ratio to 1.01 - junction jumps
    fall to the within-segment noise floor, which is what "one continuous
    curve" means numerically.
    """
    count = len(coordinates)
    spans = [
        max((coordinates[(index + 1) % count] - coordinates[index]).length, 1.0e-9)
        for index in range(count)
    ]
    right_hand = [
        (
            (coordinates[index] - coordinates[index - 1])
            * (spans[index] / spans[index - 1])
            + (coordinates[(index + 1) % count] - coordinates[index])
            * (spans[index - 1] / spans[index])
        )
        * 3.0
        for index in range(count)
    ]
    tangents = [
        (coordinates[(index + 1) % count] - coordinates[index - 1]).normalized()
        for index in range(count)
    ]
    for _pass in range(passes):
        for index in range(count):
            tangents[index] = (
                right_hand[index]
                - tangents[index - 1] * spans[index]
                - tangents[(index + 1) % count] * spans[index - 1]
            ) / (2.0 * (spans[index - 1] + spans[index]))
    return tangents, spans


def _set_c2_tangent_handles(spline, guard=True):
    """Write the C2 solution into this spline's Bezier handles.

    The representation does not change: a C2 interpolating cubic spline is
    expressible exactly in Bezier form, with each handle at one third of its
    own span along the solved tangent. The curve stays an editable cyclic
    Bezier, so every editor, the projection and the cutter are unaffected.
    """
    points = spline.bezier_points
    if len(points) < 4:
        _set_clamped_tangent_handles(spline)
        return False
    coordinates = [point.co.copy() for point in points]
    tangents, spans = _periodic_c2_tangents(coordinates)
    for index, point in enumerate(points):
        point.handle_left_type = "FREE"
        point.handle_right_type = "FREE"
        point.handle_right = (
            coordinates[index] + tangents[index] * (spans[index] / 3.0)
        )
        point.handle_left = (
            coordinates[index] - tangents[index] * (spans[index - 1] / 3.0)
        )
    # C2 buys its continuity with longer handles, which pull distant stretches
    # of the perimeter toward each other: measured, the reference trimline's
    # closest non-adjacent approach halved, 23.3 -> 13.7 mm. That is still
    # safe, but on a crowded or notched curve it can fall under the cutter's
    # merge distance and return a non-manifold cut. Bounding handle length was
    # measured to be the wrong remedy - it does not restore buildability and it
    # destroys the continuity it is protecting (junction ratio 1.01 -> 14.4 at
    # 0.35 of chord, worse than the local rule this replaced). So the curve is
    # measured instead, and where C2 would bring the line dangerously close to
    # itself the whole spline falls back to the previous tangent-continuous
    # rule. Worst case is therefore exactly the old behaviour, never worse.
    # `guard` is off only while a drag is being dragged: the sweep is quadratic
    # and would run on every mouse-move event. The drag re-checks on release,
    # so no committed curve escapes it.
    if guard and _closest_self_approach(spline) < C2_MIN_SELF_GAP_M:
        _set_clamped_tangent_handles(spline)
        return False
    return True


# Handle models whose handles are OURS to derive: their values are a pure
# function of the control points, so any disagreement means the curve was
# edited outside the add-on's tools. LINKED_TANGENTS is excluded on purpose -
# there the orthotist set the handles deliberately and they are expected to
# differ from the solved ones.
SOLVED_HANDLE_MODELS = ("C2_PERIODIC", "C2_SELF_APPROACH_FALLBACK")
# Well clear of the 0.000 mm a freshly solved curve measures and far below the
# 21 mm a hand-mangled one does.
STALE_HANDLE_LIMIT_M = 0.001


def handle_staleness_m(spline, model):
    """How far the present handles sit from the ones `model` would produce.

    Zero for any curve the add-on solved itself. Large when control points
    were moved in Blender's native curve editor, which leaves the handles
    describing the shape the curve used to have - the state that folds the
    Exact cutter into a non-manifold cut.

    The comparison is made by solving onto the real spline and restoring it,
    so it always reflects the exact production code path rather than a
    re-implementation of it that could drift.
    """
    points = spline.bezier_points
    snapshot = _capture_point_states(points)
    try:
        if model == "C2_SELF_APPROACH_FALLBACK":
            _set_clamped_tangent_handles(spline)
        else:
            _set_c2_tangent_handles(spline)
        return max(
            max(
                (point.handle_left - state[1]).length,
                (point.handle_right - state[2]).length,
            )
            for point, state in zip(points, snapshot)
        )
    finally:
        _restore_point_states(points, snapshot)


def _guard_samples(spline):
    points = spline.bezier_points
    count = len(points)
    samples = []
    for index in range(count):
        following = points[(index + 1) % count]
        samples.extend(
            interpolate_bezier(
                points[index].co,
                points[index].handle_right,
                following.handle_left,
                following.co,
                C2_GUARD_SAMPLES_PER_SEGMENT + 1,
            )[:-1]
        )
    # The sweep below is quadratic, and a refined trimline carries four times
    # the controls. Striding to a fixed budget keeps the cost flat; the
    # clearance being protected is millimetres across, far coarser than the
    # residual sample spacing.
    stride = max(1, len(samples) // C2_GUARD_SAMPLE_BUDGET)
    return samples[::stride]


def _closest_self_approach(spline):
    """Closest approach between stretches far apart ALONG the curve.

    Separation has to be circular: on a closed loop, comparing the third
    sample with the third-from-last measures immediate neighbours, not a
    near-miss between two different parts of the perimeter.
    """
    samples = _guard_samples(spline)
    count = len(samples)
    if count < 16:
        return math.inf
    skip = max(4, count // 20)
    closest = math.inf
    for first in range(count):
        for second in range(first + skip, count):
            if count - (second - first) < skip:
                continue
            closest = min(closest, (samples[first] - samples[second]).length)
    return closest


def _constrain_perimeter(perimeter, scan):
    # All joins, including the opening, are curvature-continuous.  The old
    # VECTOR override deliberately made ten 90-degree corners in the rim; the
    # local tangent rule that replaced it removed those corners but still left
    # a curvature step at every station (measured 9.7x the within-segment
    # variation), which is what read as "connected segments" rather than one
    # clinical curve.
    # Stamp what the curve actually carries. When the self-approach fallback
    # engages the handles are the old tangent-continuous ones, and recording
    # them as C2 would misreport the curve's provenance to the orthotist and
    # to any later stage that branches on this value.
    curvature_continuous = _set_c2_tangent_handles(perimeter.data.splines[0])
    perimeter["rigo_trim_handle_model"] = (
        "C2_PERIODIC" if curvature_continuous else "C2_SELF_APPROACH_FALLBACK"
    )
    modifier = perimeter.modifiers.new(name="Follow Corrected Mold", type="SHRINKWRAP")
    modifier.target = scan
    modifier.wrap_method = "NEAREST_SURFACEPOINT"
    modifier.wrap_mode = "ON_SURFACE"
    modifier.offset = SURFACE_OFFSET
    modifier.show_in_editmode = True
    modifier.show_on_cage = True


def _template_value(values, theta):
    """Circular linear interpolation of a normalized trim template."""
    count = len(values)
    position = ((theta + math.pi) / (2.0 * math.pi) * count) - 0.5
    lower = math.floor(position)
    fraction = position - lower
    first = values[lower % count]
    second = values[(lower + 1) % count]
    if first is None:
        first = second
    if second is None:
        second = first
    return first + (second - first) * fraction


class RIGO_OT_auto_trimline(Operator):
    """Drape the selected Rigo type's trim lines onto the scan (from landmarks)"""

    bl_idname = "rigo.auto_trimline"
    bl_label = "Auto Trim Lines"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _scan_of(context) is not None

    def execute(self, context):
        settings = context.scene.rigo_brace
        scan = _scan_of(context)
        if scan is None:
            self.report({"ERROR"}, "Import and prepare a scan first")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        tpl = trim_templates.load_template(settings.trim_type)
        if tpl is None:
            self.report({"ERROR"}, f"No template for type '{settings.trim_type}'")
            return {"CANCELLED"}

        z_bottom, z_waist, z_top, axis, front, warnings = _anchors(context, scan)
        if z_top <= z_waist or z_waist <= z_bottom:
            self.report(
                {"ERROR"},
                "Landmark heights are inconsistent (need bottom < waist < top) — "
                "check trochanters / waistline / acromions",
            )
            return {"CANCELLED"}

        deps = context.evaluated_depsgraph_get()
        bvh = BVHTree.FromObject(scan, deps)  # object space (as in vent_ops)
        inv = scan.matrix_world.inverted()
        inv3 = inv.to_3x3()
        mw = scan.matrix_world
        normal_matrix = inv.transposed().to_3x3()
        # Reach beyond the widest extent so drape rays always start outside.
        cs = [scan.matrix_world @ Vector(c) for c in scan.bound_box]
        reach = max(
            max(c.x for c in cs) - min(c.x for c in cs),
            max(c.y for c in cs) - min(c.y for c in cs),
        )

        def denorm(zn):
            if zn <= 0.0:
                return z_waist + zn * (z_waist - z_bottom)
            return z_waist + zn * (z_top - z_waist)

        nb = tpl["theta_bins"]
        fx, fy = front.x, front.y
        fallback_count = 0

        def drape_point(theta, z_normalized):
            nonlocal fallback_count
            dx = fx * math.cos(theta) - fy * math.sin(theta)
            dy = fx * math.sin(theta) + fy * math.cos(theta)
            direction = Vector((dx, dy, 0.0))
            z = denorm(z_normalized)
            origin_world = Vector((axis.x, axis.y, z)) + direction * reach
            origin_local = inv @ origin_world
            direction_local = (inv3 @ (-direction)).normalized()
            far_local = inv @ (origin_world - direction * (reach * 2.0))
            local_distance = (far_local - origin_local).length
            hit = bvh.ray_cast(origin_local, direction_local, local_distance)
            if hit[0] is None:
                hit = bvh.find_nearest(origin_local, local_distance)
                if hit[0] is None:
                    return None
                fallback_count += 1
            normal_world = (normal_matrix @ hit[1]).normalized()
            return mw @ hit[0] + normal_world * SURFACE_OFFSET

        def drape(z_norm_list, step):
            pts = []
            for i in range(0, nb, step):
                zn = z_norm_list[i]
                if zn is None:
                    continue
                th = -math.pi + (i + 0.5) * 2.0 * math.pi / nb
                point = drape_point(th, zn)
                if point is not None:
                    pts.append(point)
            return pts

        top_pts = drape(tpl["z_top_norm"], 3)   # 24 control points
        bot_pts = drape(tpl["z_bot_norm"], 3)
        if len(top_pts) < 8 or len(bot_pts) < 8:
            self.report(
                {"ERROR"},
                f"Could not fit trim to scan (top {len(top_pts)}/24, "
                f"bottom {len(bot_pts)}/24). Check units, orientation and landmarks",
            )
            return {"CANCELLED"}

        top = _make_trim_curve(context, TRIM_TOP_NAME, top_pts, (0.9, 0.15, 0.1, 1.0))
        bot = _make_trim_curve(context, TRIM_BOT_NAME, bot_pts, (0.1, 0.8, 0.2, 1.0))
        # The UI expresses the closure in real millimetres. Convert the requested
        # chord width to an angle at the anterior waist radius of this patient.
        waist_front = drape_point(0.0, 0.0)
        if waist_front is None:
            self.report({"ERROR"}, "Could not measure the anterior waist radius")
            return {"CANCELLED"}
        waist_radius = Vector((
            waist_front.x - axis.x,
            waist_front.y - axis.y,
        )).length
        half_chord = settings.opening_width * 0.0005
        half_gap = math.asin(min(0.95, half_chord / max(waist_radius, 0.001)))
        low_u = max(math.radians(2.0), half_gap)
        high_u = 2.0 * math.pi - low_u
        arc_count = 18
        arc_us = [
            low_u + (high_u - low_u) * index / (arc_count - 1)
            for index in range(arc_count)
        ]

        def signed_theta(u):
            return u if u <= math.pi else u - 2.0 * math.pi

        def trim_values(u):
            theta = signed_theta(u)
            return (
                _template_value(tpl["z_top_norm"], theta),
                _template_value(tpl["z_bot_norm"], theta),
            )

        perimeter_points = []
        for u in arc_us:
            top_normalized, _bottom_normalized = trim_values(u)
            point = drape_point(signed_theta(u), top_normalized)
            if point is not None:
                perimeter_points.append(point)
        top_high, bottom_high = trim_values(high_u)
        for fraction in (0.25, 0.5, 0.75):
            normalized = top_high + (bottom_high - top_high) * fraction
            point = drape_point(signed_theta(high_u), normalized)
            if point is not None:
                perimeter_points.append(point)
        for u in reversed(arc_us):
            _top_normalized, bottom_normalized = trim_values(u)
            point = drape_point(signed_theta(u), bottom_normalized)
            if point is not None:
                perimeter_points.append(point)
        top_low, bottom_low = trim_values(low_u)
        for fraction in (0.75, 0.5, 0.25):
            normalized = top_low + (bottom_low - top_low) * fraction
            point = drape_point(signed_theta(low_u), normalized)
            if point is not None:
                perimeter_points.append(point)

        if len(perimeter_points) < 16:
            self.report({"ERROR"}, "Could not create one continuous trim perimeter")
            return {"CANCELLED"}
        perimeter = _make_trim_curve(
            context,
            TRIM_PERIM_NAME,
            perimeter_points,
            (1.0, 0.55, 0.05, 1.0),
        )
        _constrain_perimeter(perimeter, scan)
        top.hide_set(True)
        bot.hide_set(True)
        # Stamp the parameterization so Generate reuses it verbatim.
        for ob in (top, bot, perimeter):
            ob["rigo_trim_axis"] = (axis.x, axis.y)
            ob["rigo_trim_front"] = (front.x, front.y)
            ob["rigo_trim_type"] = settings.trim_type
            ob["requires_orthotist_review"] = True
        perimeter["rigo_trim_opening_mm"] = settings.opening_width
        perimeter["rigo_trim_opening_deg"] = math.degrees(2.0 * low_u)
        perimeter["rigo_trim_fallback_points"] = fallback_count
        perimeter["rigo_trim_refined"] = False
        perimeter["rigo_trim_dense_controls"] = len(
            perimeter.data.splines[0].bezier_points
        )
        mark_brace_dirty(context, "Trim perimeter regenerated")
        from .design_ops import _set_design_view

        _set_design_view(context, "TRIM")

        for w in warnings:
            self.report({"WARNING"}, w)
        if fallback_count:
            self.report(
                {"WARNING"},
                f"Fitted {fallback_count} shoulder/edge points by nearest surface; "
                "review all views",
            )
        self.report(
            {"INFO"},
            f"Type {settings.trim_type} trim lines draped — refine the points, "
            "then Generate",
        )
        return {"FINISHED"}


class RIGO_OT_edit_trimline(Operator):
    """Compatibility entry point for the protected on-body trim editor."""

    bl_idname = "rigo.edit_trimline"
    bl_label = "Edit Trim Line"
    bl_options = {"REGISTER", "UNDO"}

    which: bpy.props.EnumProperty(
        items=(
            ("PERIMETER", "Perimeter", ""),
            ("TOP", "Top (legacy)", ""),
            ("BOTTOM", "Bottom (legacy)", ""),
        ),
        default="PERIMETER",
    )

    @classmethod
    def poll(cls, context):
        return (
            bpy.data.objects.get(TRIM_PERIM_NAME) is not None
            or bpy.data.objects.get(TRIM_TOP_NAME) is not None
            or bpy.data.objects.get(TRIM_BOT_NAME) is not None
        )

    def execute(self, context):
        if context.area is None or context.area.type != "VIEW_3D":
            self.report({"ERROR"}, "Open Edit on Body from the 3D viewport")
            return {"CANCELLED"}
        return bpy.ops.rigo.slide_trimline_on_surface("INVOKE_DEFAULT")


def _nearest_surface_sample_world(scan, bvh, world_point):
    inverse = scan.matrix_world.inverted()
    hit = bvh.find_nearest(inverse @ world_point)
    if hit[0] is None:
        return None, None
    normal_matrix = scan.matrix_world.inverted().transposed().to_3x3()
    normal_world = (normal_matrix @ hit[1]).normalized()
    fitted_world = scan.matrix_world @ hit[0] + normal_world * SURFACE_OFFSET
    return fitted_world, normal_world


def _nearest_surface_world(scan, bvh, world_point):
    fitted_world, _normal_world = _nearest_surface_sample_world(
        scan, bvh, world_point
    )
    return fitted_world


def _fit_curve_controls(context, curve, scan):
    bvh = BVHTree.FromObject(scan, context.evaluated_depsgraph_get())
    inverse_curve = curve.matrix_world.inverted()
    fitted = 0
    moved = 0
    for spline in curve.data.splines:
        for point in spline.bezier_points:
            fitted_world = _nearest_surface_world(
                scan, bvh, curve.matrix_world @ point.co
            )
            if fitted_world is not None:
                fitted_local = inverse_curve @ fitted_world
                if (point.co - fitted_local).length > 1.0e-7:
                    moved += 1
                point.co = fitted_local
                fitted += 1
    curve.data.update_tag()
    return fitted, moved


def _fit_curve_points(context, curve, scan):
    fitted, moved = _fit_curve_controls(context, curve, scan)
    for spline in curve.data.splines:
        _set_c2_tangent_handles(spline)
    curve.data.update_tag()
    return fitted, moved


def _curve_angle(world_coordinate, axis, front):
    relative_x = world_coordinate.x - axis[0]
    relative_y = world_coordinate.y - axis[1]
    fx, fy = front
    return math.atan2(
        relative_x * (-fy) + relative_y * fx,
        relative_x * fx + relative_y * fy,
    )


def _angle_distance(first, second):
    return abs(math.atan2(math.sin(first - second), math.cos(first - second)))


def _cyclic_arc_distances(coordinates, center_index):
    count = len(coordinates)
    distances = [float("inf")] * count
    distances[center_index] = 0.0
    for direction in (-1, 1):
        travelled = 0.0
        previous = center_index
        for step in range(1, count):
            current = (center_index + direction * step) % count
            travelled += (coordinates[current] - coordinates[previous]).length
            distances[current] = min(distances[current], travelled)
            previous = current
    return distances


def _opening_locked_indices(curve, coordinates):
    axis = tuple(curve.get("rigo_trim_axis", (0.0, 0.0)))
    front = tuple(curve.get("rigo_trim_front", (0.0, -1.0)))
    if len(axis) != 2 or len(front) != 2:
        return set()
    angles = [_curve_angle(coordinate, axis, front) for coordinate in coordinates]
    return {
        index
        for index, angle in enumerate(angles)
        if _angle_distance(angle, angles[index - 1]) <= 0.015
        or _angle_distance(angle, angles[(index + 1) % len(angles)]) <= 0.015
    }


def _valid_cyclic_controls(coordinates):
    return all(
        (coordinate - coordinates[index - 1]).length >= 0.0002
        for index, coordinate in enumerate(coordinates)
    )


def _brush_affected_indices(curve, coordinates, distances, config):
    locked = (
        _opening_locked_indices(curve, coordinates)
        if config.lock_opening
        else set()
    )
    return frozenset(
        index
        for index, distance in enumerate(distances)
        if distance < config.radius_m
        and index in config.visible_indices
        and index not in locked
    )


def _relax_trim_iteration(scan, bvh, coordinates, brush_state):
    updates = list(coordinates)
    strength = max(0.0, min(1.0, brush_state.config.strength))
    maximum_step = min(
        0.00075,
        max(0.00015, brush_state.config.radius_m * 0.015),
    )
    for index in brush_state.affected:
        current = coordinates[index]
        previous = coordinates[index - 1]
        following = coordinates[(index + 1) % len(coordinates)]
        previous_length = (current - previous).length
        following_length = (following - current).length
        total_length = previous_length + following_length
        if total_length <= 1.0e-9:
            continue
        target = previous.lerp(following, previous_length / total_length)
        _surface, normal = _nearest_surface_sample_world(scan, bvh, current)
        if normal is None:
            continue
        displacement = target - current
        displacement -= normal * displacement.dot(normal)
        falloff = 0.5 * (
            1.0
            + math.cos(
                math.pi
                * brush_state.distances[index]
                / brush_state.config.radius_m
            )
        )
        displacement *= strength * falloff
        if displacement.length > maximum_step:
            displacement.length = maximum_step
        fitted, _normal = _nearest_surface_sample_world(
            scan,
            bvh,
            current + displacement,
        )
        if fitted is not None:
            updates[index] = fitted
    return updates


def _write_world_controls(points, inverse_curve, coordinates):
    for point, coordinate in zip(points, coordinates):
        point.co = inverse_curve @ coordinate


def _smooth_trim_controls_local(
    curve,
    scan,
    bvh,
    config,
):
    """Relax a compact arc of trim controls in the scan tangent plane."""
    if len(curve.data.splines) != 1:
        raise ValueError("Smooth Trimline Brush requires one perimeter spline")
    spline = curve.data.splines[0]
    points = spline.bezier_points
    if not spline.use_cyclic_u or len(points) < 3:
        raise ValueError("Smooth Trimline Brush requires a cyclic Bezier perimeter")
    if config.center_index < 0 or config.center_index >= len(points):
        raise IndexError("Brush centre is outside the trim control range")

    matrix = curve.matrix_world
    inverse_curve = matrix.inverted()
    initial = [matrix @ point.co for point in points]
    distances = _cyclic_arc_distances(initial, config.center_index)
    affected = _brush_affected_indices(curve, initial, distances, config)
    if not affected:
        return _TrimBrushOutcome(affected=0, maximum_movement_mm=0.0)

    brush_state = _TrimBrushState(affected, tuple(distances), config)
    for _iteration in range(TRIM_BRUSH_ITERATIONS):
        original = [matrix @ point.co for point in points]
        updates = _relax_trim_iteration(scan, bvh, original, brush_state)
        if not _valid_cyclic_controls(updates):
            break
        _write_world_controls(points, inverse_curve, updates)

    # Re-solve rather than rebuilding the brushed arc with the local rule.
    # Mixing the two models in one curve is the same defect that was already
    # fixed on the drag path: the seam between local handles on the brushed
    # arc and solved handles either side is a curvature step, and it produced
    # a rim overlap that cancelled the build after an ordinary brush stroke
    # (trimqualitytest, which passes at P1). One model end to end, so the
    # stamp stays truthful and the pre-flight sees zero staleness.
    _set_c2_tangent_handles(spline)
    curve["rigo_trim_handle_model"] = "C2_PERIODIC"
    curve.data.update_tag()
    final = [matrix @ point.co for point in points]
    maximum_movement = max(
        (after - before).length for before, after in zip(initial, final)
    )
    return _TrimBrushOutcome(
        affected=len(affected),
        maximum_movement_mm=maximum_movement * 1000.0,
    )


def _refined_point_states(spline):
    points = spline.bezier_points
    splits = []
    for index, first in enumerate(points):
        second = points[(index + 1) % len(points)]
        first_level_left = (first.co + first.handle_right) * 0.5
        first_level_middle = (
            first.handle_right + second.handle_left
        ) * 0.5
        first_level_right = (second.handle_left + second.co) * 0.5
        second_level_left = (
            first_level_left + first_level_middle
        ) * 0.5
        second_level_right = (
            first_level_middle + first_level_right
        ) * 0.5
        midpoint = (second_level_left + second_level_right) * 0.5
        splits.append(
            (
                first_level_left,
                second_level_left,
                midpoint,
                second_level_right,
                first_level_right,
            )
        )
    states = []
    for index, point in enumerate(points):
        previous_split = splits[index - 1]
        current_split = splits[index]
        states.extend(
            (
                (point.co.copy(), previous_split[4], current_split[0]),
                (current_split[2], current_split[1], current_split[3]),
            )
        )
    return states


def _replace_spline_with_refined_controls(curve):
    old_spline = curve.data.splines[0]
    states = _refined_point_states(old_spline)
    curve.data.splines.remove(old_spline)
    spline = curve.data.splines.new("BEZIER")
    spline.use_cyclic_u = True
    spline.bezier_points.add(len(states) - 1)
    for point, state in zip(spline.bezier_points, states):
        point.co = state[0]
        point.handle_left_type = "FREE"
        point.handle_right_type = "FREE"
        point.handle_left = state[1]
        point.handle_right = state[2]
    curve.data.update_tag()
    return len(states)


def _radial_fit_context(context, curve, scan):
    axis = tuple(curve.get("rigo_trim_axis", (0.0, 0.0)))
    front = tuple(curve.get("rigo_trim_front", (0.0, -1.0)))
    scan_matrix = scan.matrix_world.copy()
    scan_inverse = scan_matrix.inverted()
    corners = [scan_matrix @ Vector(corner) for corner in scan.bound_box]
    reach = max(
        max(corner.x for corner in corners) - min(corner.x for corner in corners),
        max(corner.y for corner in corners) - min(corner.y for corner in corners),
    )
    return _RadialFitContext(
        axis,
        front,
        scan_matrix,
        scan_inverse,
        scan_inverse.to_3x3(),
        scan_inverse.transposed().to_3x3(),
        BVHTree.FromObject(scan, context.evaluated_depsgraph_get()),
        reach,
    )


def _radial_surface_world(fit, coordinate):
    angle = _curve_angle(coordinate, fit.axis, fit.front)
    fx, fy = fit.front
    radial = Vector(
        (
            fx * math.cos(angle) - fy * math.sin(angle),
            fx * math.sin(angle) + fy * math.cos(angle),
            0.0,
        )
    )
    origin = Vector((*fit.axis, coordinate.z)) + radial * fit.reach
    origin_local = fit.scan_inverse @ origin
    direction_local = (fit.inverse_3 @ (-radial)).normalized()
    hit = fit.bvh.ray_cast(origin_local, direction_local, fit.reach * 2.0)
    if hit[0] is None:
        hit = fit.bvh.find_nearest(fit.scan_inverse @ coordinate)
    if hit[0] is None:
        return None
    normal = (fit.normal_matrix @ hit[1]).normalized()
    return fit.scan_matrix @ hit[0] + normal * SURFACE_OFFSET


def _fit_refined_controls(context, curve, scan):
    fit = _radial_fit_context(context, curve, scan)
    inverse_curve = curve.matrix_world.inverted()
    for point in curve.data.splines[0].bezier_points:
        fitted = _radial_surface_world(fit, curve.matrix_world @ point.co)
        if fitted is None:
            continue
        delta = inverse_curve @ fitted - point.co
        point.co += delta
        point.handle_left += delta
        point.handle_right += delta
    curve.data.update_tag()


class RIGO_OT_refine_trimline(Operator):
    """Double editable controls and fit the new points back onto the body"""

    bl_idname = "rigo.refine_trimline"
    bl_label = "Add Curve Detail"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            bpy.data.objects.get(TRIM_PERIM_NAME) is not None
            and _scan_of(context) is not None
        )

    def execute(self, context):
        curve = bpy.data.objects.get(TRIM_PERIM_NAME)
        scan = _scan_of(context)
        if curve is None or scan is None:
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        point_count = len(curve.data.splines[0].bezier_points)
        if point_count >= 168:
            self.report(
                {"WARNING"},
                "Trimline already has maximum editable refinement (168 points)",
            )
            return {"CANCELLED"}
        refined_count = _replace_spline_with_refined_controls(curve)
        _fit_refined_controls(context, curve, scan)
        curve["rigo_trim_handle_model"] = "REFINED_SURFACE_FIT"
        curve["rigo_trim_refined"] = True
        mark_brace_dirty(context, "Trimline edit resolution refined")
        from .design_ops import _set_design_view

        _set_design_view(context, "TRIM")
        self.report(
            {"INFO"},
            f"Trimline refined from {point_count} to {refined_count} controls",
        )
        return {"FINISHED"}


def _activate_trim_curve(context, curve):
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    curve.hide_set(False)
    curve.select_set(True)
    context.view_layer.objects.active = curve
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.curve.select_all(action="DESELECT")


def _point_visible_from_view(scan, bvh, origin_world, point_world):
    """True when no body surface blocks this control point from the view."""
    direction_world = origin_world - point_world
    if direction_world.length <= 1.0e-9:
        return False
    direction_world.normalize()
    start_world = point_world + direction_world * 0.0002
    inverse = scan.matrix_world.inverted()
    start_local = inverse @ start_world
    view_local = inverse @ origin_world
    ray_local = view_local - start_local
    hit = bvh.ray_cast(start_local, ray_local.normalized(), ray_local.length)
    return hit[0] is None


def _event_window_coordinates(event, region):
    """Return coordinates relative to the stored VIEW_3D WINDOW region."""
    if hasattr(event, "mouse_x") and hasattr(event, "mouse_y"):
        return Vector((event.mouse_x - region.x, event.mouse_y - region.y))
    return Vector((event.mouse_region_x, event.mouse_region_y))


def _view_origin_clamp(scan, region_3d):
    """Keep orthographic ray origins precise around the current scan."""
    view_location = Vector(region_3d.view_location)
    corners_world = [
        scan.matrix_world @ Vector(corner) for corner in scan.bound_box
    ]
    furthest_corner = max(
        (corner - view_location).length for corner in corners_world
    )
    return max(1.0, furthest_corner * 2.0)


def _view_ray_origin(region, region_3d, coordinates, scan):
    # The application template uses a 100 km far clip; Blender explicitly
    # recommends clamping orthographic origins to avoid precision loss.
    return view3d_utils.region_2d_to_origin_3d(
        region,
        region_3d,
        coordinates,
        clamp=_view_origin_clamp(scan, region_3d),
    )


def _raycast_scan_surface(ray_context, event):
    mouse = _event_window_coordinates(event, ray_context.region)
    origin_world = _view_ray_origin(
        ray_context.region,
        ray_context.region_3d,
        mouse,
        ray_context.scan,
    )
    direction_world = view3d_utils.region_2d_to_vector_3d(
        ray_context.region, ray_context.region_3d, mouse
    )
    inverse = ray_context.scan.matrix_world.inverted()
    origin_local = inverse @ origin_world
    target_local = inverse @ (origin_world + direction_world)
    direction_local = (target_local - origin_local).normalized()
    hit = ray_context.bvh.ray_cast(origin_local, direction_local)
    if hit[0] is None:
        return None
    normal_matrix = (
        ray_context.scan.matrix_world.inverted().transposed().to_3x3()
    )
    normal_world = (normal_matrix @ hit[1]).normalized()
    return (
        ray_context.scan.matrix_world @ hit[0]
        + normal_world * SURFACE_OFFSET
    )


def _pick_visible_element(
    region,
    region_3d,
    event,
    curve,
    scan,
    bvh,
    points,
    radius_pixels=18.0,
):
    """Pick a front-side control point or either of its Bezier handles."""
    mouse = _event_window_coordinates(event, region)
    nearest_element = None
    nearest_distance = radius_pixels
    matrix = curve.matrix_world
    for index, point in enumerate(points):
        point_world = matrix @ point.co
        point_screen = view3d_utils.location_3d_to_region_2d(
            region, region_3d, point_world
        )
        if point_screen is None:
            continue
        origin_world = _view_ray_origin(
            region, region_3d, point_screen, scan
        )
        if not _point_visible_from_view(scan, bvh, origin_world, point_world):
            continue
        candidates = [("CONTROL", point.co)]
        if (
            point.select_control_point
            or point.select_left_handle
            or point.select_right_handle
        ):
            candidates.extend(
                (
                    ("LEFT_HANDLE", point.handle_left),
                    ("RIGHT_HANDLE", point.handle_right),
                )
            )
        for element_kind, coordinate in candidates:
            screen = view3d_utils.location_3d_to_region_2d(
                region, region_3d, matrix @ coordinate
            )
            if screen is None:
                continue
            distance = (screen - mouse).length
            if distance >= nearest_distance:
                continue
            nearest_element = (index, element_kind)
            nearest_distance = distance
    return nearest_element


def _capture_point_states(points):
    return [
        (
            point.co.copy(),
            point.handle_left.copy(),
            point.handle_right.copy(),
            point.handle_left_type,
            point.handle_right_type,
        )
        for point in points
    ]


def _restore_point_states(points, states):
    for point, state in zip(points, states):
        point.co = state[0]
        point.handle_left_type = "FREE"
        point.handle_right_type = "FREE"
        point.handle_left = state[1]
        point.handle_right = state[2]
        point.handle_left_type = state[3]
        point.handle_right_type = state[4]


def _point_states_changed(points, states):
    return any(
        (point.co - state[0]).length > 1.0e-9
        or (point.handle_left - state[1]).length > 1.0e-9
        or (point.handle_right - state[2]).length > 1.0e-9
        or point.handle_left_type != state[3]
        or point.handle_right_type != state[4]
        for point, state in zip(points, states)
    )


def _bounded_handle_coordinate(control, adjacent_coordinates, requested):
    previous, following = adjacent_coordinates
    direction = requested - control
    maximum_reach = 0.75 * min(
        (control - previous).length,
        (following - control).length,
    )
    if direction.length > maximum_reach:
        direction.length = maximum_reach
    return control + direction


def _linked_handle_coordinates(
    control,
    adjacent_coordinates,
    requested,
    opposite_coordinate,
):
    """Return a bounded dragged handle and its G1-linked opposite partner."""
    dragged = _bounded_handle_coordinate(
        control, adjacent_coordinates, requested
    )
    direction = dragged - control
    if direction.length_squared <= 1.0e-20:
        return dragged, opposite_coordinate.copy()
    maximum_reach = 0.75 * min(
        (control - adjacent_coordinates[0]).length,
        (adjacent_coordinates[1] - control).length,
    )
    opposite_length = min(
        (opposite_coordinate - control).length,
        maximum_reach,
    )
    opposite = control - direction.normalized() * opposite_length
    return dragged, opposite


class RIGO_OT_snap_trimline_to_surface(Operator):
    """Project every perimeter control point back onto the corrected body"""

    bl_idname = "rigo.snap_trimline_to_surface"
    bl_label = "Fit Line to Body"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            bpy.data.objects.get(TRIM_PERIM_NAME) is not None
            and _scan_of(context) is not None
        )

    def execute(self, context):
        curve = bpy.data.objects.get(TRIM_PERIM_NAME)
        scan = _scan_of(context)
        if curve is None or scan is None:
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        fitted, moved = _fit_curve_points(context, curve, scan)
        if moved:
            mark_brace_dirty(context, "Trim perimeter fitted to body")
            from .design_ops import _set_design_view

            _set_design_view(context, "TRIM")
        self.report(
            {"INFO"}, f"Fitted {fitted} trim points; moved {moved} back to the body"
        )
        return {"FINISHED"}


class RIGO_OT_smooth_trimline_brush(Operator):
    """Paint a local, surface-following relaxation along the trim perimeter"""

    bl_idname = "rigo.smooth_trimline_brush"
    bl_label = "Smooth Trimline Brush"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == "VIEW_3D"
            and bpy.data.objects.get(TRIM_PERIM_NAME) is not None
            and _scan_of(context) is not None
        )

    def invoke(self, context, _event):
        self._curve = bpy.data.objects.get(TRIM_PERIM_NAME)
        self._scan = _scan_of(context)
        self._area = context.area
        self._region = next(
            (region for region in context.area.regions if region.type == "WINDOW"),
            None,
        )
        self._region_3d = context.area.spaces.active.region_3d
        if self._curve is None or self._scan is None:
            return {"CANCELLED"}
        if self._region is None or self._region_3d is None:
            self.report({"ERROR"}, "Could not access the 3D viewport window")
            return {"CANCELLED"}
        try:
            self._prepare(context)
        except Exception as error:
            self.report({"ERROR"}, f"Could not start Smooth Trimline Brush: {error}")
            return {"CANCELLED"}
        context.window_manager.modal_handler_add(self)
        self._area.header_text_set(
            "Smooth Trimline: left-drag over the line | Enter = finish | "
            "Ctrl+Z = undo stroke | Esc = cancel all"
        )
        return {"RUNNING_MODAL"}

    def _prepare(self, context):
        if self._curve.type != "CURVE" or len(self._curve.data.splines) != 1:
            raise ValueError("the trim perimeter must contain one curve spline")
        spline = self._curve.data.splines[0]
        if spline.type != "BEZIER" or not spline.use_cyclic_u:
            raise ValueError("the trim perimeter must be a closed Bezier curve")
        from .design_ops import _set_design_view

        _set_design_view(context, "TRIM")
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        self._curve.hide_set(False)
        self._curve.select_set(True)
        context.view_layer.objects.active = self._curve
        self._points = list(spline.bezier_points)
        self._snapshot = _capture_point_states(self._points)
        self._snapshot_handle_model = str(
            self._curve.get("rigo_trim_handle_model", "CLAMPED_TANGENT")
        )
        self._show_in_front = self._curve.show_in_front
        self._curve.show_in_front = False
        self._bvh = BVHTree.FromObject(
            self._scan, context.evaluated_depsgraph_get()
        )
        self._ray_context = _SurfaceRayContext(
            self._region,
            self._region_3d,
            self._scan,
            self._bvh,
        )
        self._painting = False
        self._stroke_start = None
        self._stroke_handle_model = None
        self._stroke_changed = False
        self._last_edit = None
        self._last_handle_model = None
        self._changed = False
        self._maximum_movement_mm = 0.0
        self._cursor_world = None
        self._last_dab_world = None
        self._curve["rigo_trim_brush_status"] = "READY"
        self._curve["rigo_trim_brush_affected"] = 0
        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_cursor,
            (),
            "WINDOW",
            "POST_PIXEL",
        )

    def _visible_indices(self):
        visible = set()
        matrix = self._curve.matrix_world
        for index, point in enumerate(self._points):
            point_world = matrix @ point.co
            screen = view3d_utils.location_3d_to_region_2d(
                self._region, self._region_3d, point_world
            )
            if screen is None:
                continue
            origin_world = _view_ray_origin(
                self._region, self._region_3d, screen, self._scan
            )
            if _point_visible_from_view(
                self._scan, self._bvh, origin_world, point_world
            ):
                visible.add(index)
        return visible

    def _nearest_control(self, world_coordinate, visible, radius_m):
        matrix = self._curve.matrix_world
        candidates = (
            ((matrix @ self._points[index].co - world_coordinate).length, index)
            for index in visible
        )
        nearest = min(candidates, default=None)
        if nearest is None or nearest[0] > radius_m:
            return None
        return nearest[1]

    def _dab(self, context, event):
        world = _raycast_scan_surface(self._ray_context, event)
        self._cursor_world = world
        if world is None:
            self._curve["rigo_trim_brush_status"] = "NO_SURFACE_HIT"
            return False
        settings = context.scene.rigo_brace
        radius_m = settings.trim_brush_radius * 0.001
        visible = self._visible_indices()
        center_index = self._nearest_control(world, visible, radius_m)
        if center_index is None:
            self._curve["rigo_trim_brush_status"] = "NOT_OVER_VISIBLE_LINE"
            self._area.header_text_set(
                "Brush is not over a visible trimline | Enter = finish | Esc = cancel"
            )
            return False
        brush_config = _TrimBrushConfig(
            center_index=center_index,
            radius_m=radius_m,
            strength=settings.trim_brush_strength,
            visible_indices=frozenset(visible),
            lock_opening=settings.trim_brush_lock_opening,
        )
        brush_outcome = _smooth_trim_controls_local(
            self._curve,
            self._scan,
            self._bvh,
            brush_config,
        )
        affected = brush_outcome.affected
        if not affected:
            self._curve["rigo_trim_brush_status"] = "OPENING_LOCKED"
            self._area.header_text_set(
                "Opening controls are locked | disable Lock Opening Corners to edit them"
            )
            return False
        self._maximum_movement_mm = max(
            self._maximum_movement_mm,
            brush_outcome.maximum_movement_mm,
        )
        self._curve["rigo_trim_handle_model"] = "LINKED_TANGENTS"
        self._curve["rigo_trim_brush_status"] = "SMOOTHED"
        self._curve["rigo_trim_brush_affected"] = affected
        self._curve.data.update_tag()
        self._last_dab_world = world
        self._area.header_text_set(
            f"Smoothed {affected} controls locally | Enter = finish | "
            "Ctrl+Z = undo stroke | Esc = cancel all"
        )
        return True

    def _should_dab(self, context, event):
        if self._last_dab_world is None:
            return True
        world = _raycast_scan_surface(self._ray_context, event)
        self._cursor_world = world
        if world is None:
            return False
        spacing = context.scene.rigo_brace.trim_brush_radius * 0.00012
        return (world - self._last_dab_world).length >= spacing

    def _draw_cursor(self):
        if self._cursor_world is None:
            return
        center = view3d_utils.location_3d_to_region_2d(
            self._region, self._region_3d, self._cursor_world
        )
        if center is None:
            return
        radius_m = bpy.context.scene.rigo_brace.trim_brush_radius * 0.001
        view_right = self._region_3d.view_rotation @ Vector((1.0, 0.0, 0.0))
        edge = view3d_utils.location_3d_to_region_2d(
            self._region,
            self._region_3d,
            self._cursor_world + view_right * radius_m,
        )
        if edge is None:
            return
        radius_pixels = max(4.0, (edge - center).length)
        positions = [
            (
                center.x + radius_pixels * math.cos(step * math.tau / 64.0),
                center.y + radius_pixels * math.sin(step * math.tau / 64.0),
            )
            for step in range(65)
        ]
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = batch_for_shader(shader, "LINE_STRIP", {"pos": positions})
        gpu.state.blend_set("ALPHA")
        gpu.state.line_width_set(2.0)
        shader.bind()
        shader.uniform_float("color", (0.2, 0.75, 1.0, 0.9))
        batch.draw(shader)
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set("NONE")

    def _begin_stroke(self, context, event):
        self._painting = True
        self._stroke_start = _capture_point_states(self._points)
        self._stroke_handle_model = str(
            self._curve.get("rigo_trim_handle_model", "CLAMPED_TANGENT")
        )
        self._stroke_changed = self._dab(context, event)

    def _commit_stroke(self):
        if self._stroke_changed:
            self._last_edit = self._stroke_start
            self._last_handle_model = self._stroke_handle_model
            self._changed = True
        self._painting = False
        self._stroke_start = None
        self._stroke_handle_model = None
        self._stroke_changed = False
        self._last_dab_world = None

    def _undo_last_stroke(self):
        if self._last_edit is None:
            self._area.header_text_set("No smooth-brush stroke to undo")
            return
        _restore_point_states(self._points, self._last_edit)
        self._curve["rigo_trim_handle_model"] = self._last_handle_model
        self._curve.data.update_tag()
        self._last_edit = None
        self._last_handle_model = None
        self._changed = _point_states_changed(self._points, self._snapshot)
        self._area.header_text_set(
            "Last smooth-brush stroke restored | Enter = finish | Esc = cancel all"
        )

    def _cleanup(self):
        if getattr(self, "_draw_handle", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, "WINDOW")
            self._draw_handle = None
        if self._area is not None:
            self._area.header_text_set(None)
            self._area.tag_redraw()
        self._curve.show_in_front = self._show_in_front

    def _finish(self, context, cancelled):
        if cancelled:
            _restore_point_states(self._points, self._snapshot)
            self._curve["rigo_trim_handle_model"] = self._snapshot_handle_model
            self._curve.data.update_tag()
        elif self._changed:
            mark_brace_dirty(context, "Trim perimeter locally smoothed")
        self._cleanup()
        if not cancelled and self._changed:
            self.report(
                {"INFO"},
                "Trimline brush committed; maximum control movement "
                f"{self._maximum_movement_mm:.2f} mm",
            )
        return {"CANCELLED"} if cancelled else {"FINISHED"}

    def _fail(self, context, error):
        _restore_point_states(self._points, self._snapshot)
        self._curve["rigo_trim_handle_model"] = self._snapshot_handle_model
        self._curve.data.update_tag()
        self._cleanup()
        self.report({"ERROR"}, f"Smooth Trimline Brush cancelled safely: {error}")
        return {"CANCELLED"}

    def modal(self, context, event):
        try:
            if event.type == "ESC" and event.value == "PRESS":
                return self._finish(context, True)
            if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
                return self._finish(context, False)
            if event.type == "Z" and event.value == "PRESS" and event.ctrl:
                self._undo_last_stroke()
                return {"RUNNING_MODAL"}
            if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
                return {"PASS_THROUGH"}
            if event.type == "LEFTMOUSE" and event.value == "PRESS":
                self._begin_stroke(context, event)
                self._area.tag_redraw()
                return {"RUNNING_MODAL"}
            if event.type == "LEFTMOUSE" and event.value == "RELEASE":
                self._commit_stroke()
                return {"RUNNING_MODAL"}
            if event.type == "MOUSEMOVE":
                if self._painting and self._should_dab(context, event):
                    self._stroke_changed = self._dab(context, event) or self._stroke_changed
                elif not self._painting:
                    self._cursor_world = _raycast_scan_surface(
                        self._ray_context, event
                    )
                self._area.tag_redraw()
                return {"RUNNING_MODAL"}
            return {"RUNNING_MODAL"}
        except Exception as error:
            return self._fail(context, error)


class RIGO_OT_slide_trimline_on_surface(Operator):
    """Drag body-bound fit points and linked Fusion-style tangent handles"""

    bl_idname = "rigo.slide_trimline_on_surface"
    bl_label = "Edit on Body"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == "VIEW_3D"
            and bpy.data.objects.get(TRIM_PERIM_NAME) is not None
            and _scan_of(context) is not None
        )

    def invoke(self, context, _event):
        self._curve = bpy.data.objects.get(TRIM_PERIM_NAME)
        self._scan = _scan_of(context)
        if self._curve is None or self._scan is None:
            return {"CANCELLED"}
        self._area = context.area
        self._region = next(
            (region for region in context.area.regions if region.type == "WINDOW"),
            None,
        )
        self._region_3d = context.area.spaces.active.region_3d
        if self._region is None or self._region_3d is None:
            self.report({"ERROR"}, "Could not access the 3D viewport window")
            return {"CANCELLED"}
        from .design_ops import _set_design_view

        _set_design_view(context, "TRIM")
        _activate_trim_curve(context, self._curve)
        self._points = [
            point
            for spline in self._curve.data.splines
            for point in spline.bezier_points
        ]
        self._snapshot = _capture_point_states(self._points)
        self._snapshot_handle_model = str(
            self._curve.get("rigo_trim_handle_model", "CLAMPED_TANGENT")
        )
        self._show_in_front = self._curve.show_in_front
        self._curve.show_in_front = False
        self._bvh = BVHTree.FromObject(
            self._scan, context.evaluated_depsgraph_get()
        )
        self._ray_context = _SurfaceRayContext(
            self._region,
            self._region_3d,
            self._scan,
            self._bvh,
        )
        self._drag_index = None
        self._drag_kind = None
        self._drag_start = None
        self._last_edit = None
        self._last_handle_model = None
        self._dragging = False
        context.window_manager.modal_handler_add(self)
        self._area.header_text_set(
            "Trim: blue point moves on body; either white handle rotates its partner | "
            "Ctrl+Z = undo drag | Enter = finish | Esc = cancel all"
        )
        return {"RUNNING_MODAL"}

    def _begin_drag(self, context, event):
        picked = self._pick_element(context, event)
        self._dragging = picked is not None
        if self._dragging:
            self._drag_index, self._drag_kind = picked
            self._drag_handle_model = str(
                self._curve.get("rigo_trim_handle_model", "CLAMPED_TANGENT")
            )
            bpy.ops.curve.select_all(action="DESELECT")
            point = self._points[self._drag_index]
            if self._drag_kind == "CONTROL":
                point.select_control_point = True
                point.select_left_handle = True
                point.select_right_handle = True
            elif self._drag_kind == "LEFT_HANDLE":
                point.select_left_handle = True
            else:
                point.select_right_handle = True
            self._drag_start = _capture_point_states(self._points)
        else:
            self._area.header_text_set(
                "No visible trim point selected | rotate to the required side | Esc = cancel"
            )

    def _move_dragged_point(self, context, event):
        world = self._raycast(context, event)
        if world is None:
            return
        inverse_curve = self._curve.matrix_world.inverted()
        target = inverse_curve @ world
        delta = target - self._drag_start[self._drag_index][0]
        point_count = len(self._points)
        affected = {}
        for offset, weight in ((0, 1.0), (-1, 0.50), (1, 0.50), (-2, 0.18), (2, 0.18)):
            index = (self._drag_index + offset) % point_count
            affected[index] = max(weight, affected.get(index, 0.0))
        for index, weight in affected.items():
            if index != self._drag_index and not self._point_is_visible(index):
                continue
            intended_local = self._drag_start[index][0] + delta * weight
            fitted_world = _nearest_surface_world(
                self._scan,
                self._bvh,
                self._curve.matrix_world @ intended_local,
            )
            if fitted_world is not None:
                self._points[index].co = inverse_curve @ fitted_world
        # Must be the SAME model the generator used. Leaving the old local rule
        # here meant the first drag re-derived every handle by a different
        # rule than the curve was built with, so the whole perimeter changed
        # shape at once - measured 19.2 mm even 60 mm away from the drag, more
        # than the 8 mm drag itself, none of it propagation. Re-solving C2
        # keeps one model end to end; that the solve is still global is P3's
        # defect, and P3's banded solve fixes locality without reintroducing a
        # second handle model.
        for spline in self._curve.data.splines:
            _set_c2_tangent_handles(spline, guard=False)
        self._curve["rigo_trim_handle_model"] = "C2_PERIODIC"
        self._curve.data.update_tag()

    def _point_is_visible(self, index):
        point_world = self._curve.matrix_world @ self._points[index].co
        screen = view3d_utils.location_3d_to_region_2d(
            self._region,
            self._region_3d,
            point_world,
        )
        if screen is None:
            return False
        origin_world = _view_ray_origin(
            self._region,
            self._region_3d,
            screen,
            self._scan,
        )
        return _point_visible_from_view(
            self._scan,
            self._bvh,
            origin_world,
            point_world,
        )

    def _move_dragged_handle(self, event):
        point = self._points[self._drag_index]
        mouse = _event_window_coordinates(event, self._region)
        point_world = self._curve.matrix_world @ point.co
        handle_world = view3d_utils.region_2d_to_location_3d(
            self._region,
            self._region_3d,
            mouse,
            point_world,
        )
        handle_local = self._curve.matrix_world.inverted() @ handle_world
        point_count = len(self._points)
        previous = self._points[(self._drag_index - 1) % point_count].co
        following = self._points[(self._drag_index + 1) % point_count].co
        state = self._drag_start[self._drag_index]
        opposite_start = state[2] if self._drag_kind == "LEFT_HANDLE" else state[1]
        dragged, opposite = _linked_handle_coordinates(
            point.co,
            (previous, following),
            handle_local,
            opposite_start,
        )
        point.handle_left_type = "FREE"
        point.handle_right_type = "FREE"
        if self._drag_kind == "LEFT_HANDLE":
            point.handle_left = dragged
            point.handle_right = opposite
        else:
            point.handle_right = dragged
            point.handle_left = opposite
        self._curve["rigo_trim_handle_model"] = "LINKED_TANGENTS"
        self._curve.data.update_tag()

    def _move_dragged_element(self, context, event):
        if self._drag_kind == "CONTROL":
            self._move_dragged_point(context, event)
        else:
            self._move_dragged_handle(event)

    def _finish(self, context, cancelled):
        if cancelled:
            _restore_point_states(self._points, self._snapshot)
            self._curve["rigo_trim_handle_model"] = self._snapshot_handle_model
            self._curve.data.update_tag()
        elif _point_states_changed(self._points, self._snapshot):
            mark_brace_dirty(context, "Trim perimeter edited")
        self._curve.show_in_front = self._show_in_front
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        if self._area is not None:
            self._area.header_text_set(None)
        return {"CANCELLED"} if cancelled else {"FINISHED"}

    def _pick_element(self, context, event):
        return _pick_visible_element(
            self._region,
            self._region_3d,
            event,
            self._curve,
            self._scan,
            self._bvh,
            self._points,
        )

    def _commit_drag(self):
        if self._drag_index is not None and self._drag_start is not None:
            # The per-move solve skips the quadratic self-approach sweep; run
            # it once here so a released drag can never leave the perimeter in
            # a state the cutter would refuse.
            if self._drag_kind == "CONTROL":
                for spline in self._curve.data.splines:
                    _set_c2_tangent_handles(spline)
                self._curve.data.update_tag()
            if _point_states_changed(self._points, self._drag_start):
                self._last_edit = self._drag_start
                self._last_handle_model = self._drag_handle_model
                if self._drag_kind != "CONTROL":
                    self._curve["rigo_trim_handle_model"] = "LINKED_TANGENTS"
        self._dragging = False
        self._drag_start = None
        self._drag_kind = None

    def _undo_last_edit(self, context):
        if self._last_edit is None:
            self._area.header_text_set("No trim-point edit to undo")
            return
        _restore_point_states(self._points, self._last_edit)
        self._curve["rigo_trim_handle_model"] = self._last_handle_model
        self._curve.data.update_tag()
        self._last_edit = None
        self._last_handle_model = None
        self._area.header_text_set(
            "Last trim-point edit restored | Enter = finish | Esc = cancel all"
        )

    def _raycast(self, context, event):
        return _raycast_scan_surface(self._ray_context, event)

    def modal(self, context, event):
        if event.type == "ESC" and event.value == "PRESS":
            return self._finish(context, True)
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            return self._finish(context, False)
        if event.type == "Z" and event.value == "PRESS" and event.ctrl:
            self._undo_last_edit(context)
            return {"RUNNING_MODAL"}
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            self._begin_drag(context, event)
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            self._commit_drag()
            return {"RUNNING_MODAL"}
        if event.type == "MOUSEMOVE" and self._dragging:
            self._move_dragged_element(context, event)
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}


class RIGO_OT_clear_trimlines(Operator):
    """Remove the auto trim lines (back to flat trims)"""

    bl_idname = "rigo.clear_trimlines"
    bl_label = "Clear Trim Lines"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        removed = 0
        for name in (TRIM_TOP_NAME, TRIM_BOT_NAME, TRIM_PERIM_NAME):
            obj = bpy.data.objects.get(name)
            if obj is not None:
                data = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if data.users == 0:
                    bpy.data.curves.remove(data)
                removed += 1
        if removed:
            mark_brace_dirty(context, "Trim perimeter cleared")
            from .design_ops import _set_design_view

            _set_design_view(context, "TRIM")
        self.report({"INFO"}, f"Removed {removed} trim line(s)")
        return {"FINISHED"}


_CLASSES = (
    RIGO_OT_auto_trimline,
    RIGO_OT_edit_trimline,
    RIGO_OT_snap_trimline_to_surface,
    RIGO_OT_smooth_trimline_brush,
    RIGO_OT_refine_trimline,
    RIGO_OT_slide_trimline_on_surface,
    RIGO_OT_clear_trimlines,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
