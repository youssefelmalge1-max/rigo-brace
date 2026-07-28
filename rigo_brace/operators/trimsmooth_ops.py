"""Smooth / Straighten Trimline — unified clinical authoring control.

One operator for every trimline source (template, painted, manual, edited,
refined): the authoritative perimeter is always the same cyclic Bezier, so the
tool operates on that single object and display, cutter and rim all consume
the result through the existing unified path.

Modes:
  SMOOTH       whole-line Gaussian fairing along arc length (sigma in mm)
  SMOOTH_ARC   the same, windowed over the selected arc with mm cosine ramps
  STRAIGHTEN   flatten the selected arc's lateral-in-view component so it
               reads straight from the chosen design view while the depth
               keeps following the target surface
  BLEND        fair a junction between adjoining arcs (window centred on it)

Every mode: kernel on the densely sampled path -> Preserve-Shape blend ->
full depth re-imposition on edited samples (interpolated normals; tangential
shape stays from the kernel, so no mold-facet stamping) -> write back to the
control stations -> banded C2 re-solve of the edited run only.

Adaptive local refinement on Apply (project-owner rules, 2026-07-28): the
refit error against the accepted path is MEASURED; only when the existing
controls cannot carry the accepted path within `refine_tolerance` are the
offending segments subdivided - exact De Casteljau, shape-preserving, inside
the edited region only, capped at 168 controls, provenance recorded in
`rigo_trim_refined_controls`. Refinement is never triggered by the slider
values themselves.

Live preview is Blender's redo-panel idiom: each parameter change undoes and
re-executes, so nothing is permanent until the user moves on, and Cancel is
native bit-exact undo.
"""

import math

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
)
from bpy.types import Operator
from mathutils import Vector

from ..core import mark_brace_dirty
from . import design_ops
from .custom_trim_ops import _smooth_closed_parametric
from .trimline_ops import (
    MANUAL_HANDLE_KEY,
    SURFACE_OFFSET,
    TRIM_PERIM_NAME,
    _opening_locked_indices,
    _scan_of,
    manual_handle_indices,
    mark_handles_solved,
    solve_band_c2,
    _set_c2_tangent_handles,
)

REFINED_CONTROLS_KEY = "rigo_trim_refined_controls"
_MAX_CONTROLS = 168
_DENSE_TOTAL = 2048          # matches curve_build_ops._curve_world_samples
_REFINE_ROUNDS = 3           # each round may split several offending segments


# --------------------------------------------------------------------------
# dense path sampling (uniform per-segment, so control k sits at k * per)

def _dense_path(spline, matrix):
    points = spline.bezier_points
    per = max(24, _DENSE_TOTAL // max(1, len(points)))
    from mathutils.geometry import interpolate_bezier

    samples = []
    for index, first in enumerate(points):
        second = points[(index + 1) % len(points)]
        segment = interpolate_bezier(
            first.co, first.handle_right, second.handle_left, second.co,
            per + 1,
        )
        samples.extend(matrix @ co for co in segment[:-1])
    return samples, per


# --------------------------------------------------------------------------
# geometry helpers

def _spacing(points):
    count = len(points)
    return [
        (points[(index + 1) % count] - points[index]).length
        for index in range(count)
    ]


def _cyclic_run(count, start, end):
    run = []
    index = start
    while True:
        run.append(index)
        if index == end:
            return run
        index = (index + 1) % count


def _arc_positions_mm(points, run):
    """Cumulative arc length along a run, in metres, starting at 0."""
    positions = [0.0]
    for step in range(1, len(run)):
        positions.append(
            positions[-1]
            + (points[run[step]] - points[run[step - 1]]).length
        )
    return positions


def _ramp_weights(points, run, ramp_m, pin_endpoints):
    """1 inside the arc, cosine-ramped over RAMP MILLIMETRES at each end.

    The prototype ramped over one station index, which meant the physical ramp
    width depended on local spacing and produced junction spikes up to 154
    degrees on the processed path. A millimetre ramp makes the transition
    width a controlled physical quantity.
    """
    count = len(points)
    weights = [0.0] * count
    positions = _arc_positions_mm(points, run)
    span = positions[-1]
    ramp = min(ramp_m, span * 0.45) if pin_endpoints else 0.0
    for step, index in enumerate(run):
        if not pin_endpoints:
            weights[index] = 1.0
            continue
        distance = min(positions[step], span - positions[step])
        if distance >= ramp or ramp <= 0.0:
            weights[index] = 1.0 if distance > 0.0 else 0.0
        else:
            weights[index] = 0.5 * (
                1.0 - math.cos(math.pi * distance / ramp)
            )
    return weights


def _landmark_zero_zones(points, weights, landmark_samples, ramp_m):
    """Zero the weight at locked landmarks, cosine-ramped over millimetres."""
    count = len(points)
    lengths = _spacing(points)
    for centre in landmark_samples:
        weights[centre] = 0.0
        for direction in (-1, 1):
            walked = 0.0
            index = centre
            while walked < ramp_m:
                index = (index + direction) % count
                walked += lengths[index if direction > 0 else (index + 1) % count]
                factor = 0.5 * (1.0 - math.cos(math.pi * min(1.0, walked / ramp_m)))
                weights[index] = min(weights[index], factor)
    return weights


def _surface_context(scan):
    """Measure against the body the orthotist actually SEES.

    `scan.data` is the raw imported mesh. The patient scan normally carries
    modifiers - Rigo Remesh / Rigo Smooth / Rigo Thickness, the derotation
    SIMPLE_DEFORM, the Bend-Twist-Stretch and correction lattices - so the
    visible body is the EVALUATED mesh, and every other stage of the trimline
    system reads it that way (`BVHTree.FromObject(scan, depsgraph)`).

    Reading `scan.data` here re-imposed the standoff against a surface that is
    not where the body is drawn. Measured, one press of Smooth All: derotation
    modifier -> controls moved up to 57.0 mm with 20 of 42 ending up INSIDE
    the torso; correction lattice -> up to 94.0 mm with 14 of 42 inside. That
    is the trimline the orthotist watched disappear. A scan with no modifiers
    (the old test fixture) is the one case where raw and evaluated agree,
    which is why the gates stayed green.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = scan.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        # `_source_surface` copies coordinates, normals and triangles into its
        # own lists and builds the BVH from those, so freeing the temporary
        # evaluated mesh afterwards is safe.
        source = design_ops._source_surface(mesh)
    finally:
        evaluated.to_mesh_clear()
    matrix = evaluated.matrix_world.copy()
    return source, matrix.inverted(), matrix, matrix.to_3x3()


def _redepth(points, edited, source, inverse, matrix, rotation, offset):
    """Re-impose the exact standoff along interpolated normals.

    Applied at FULL weight to every edited sample: the prototype scaled this
    by the window weight, which left partially-corrected depth in the ramp
    zones (measured -0.8 mm). The tangential position always stays from the
    kernel, so mold facets are never stamped into the path (LM-0035).
    """
    out = []
    for index, point in enumerate(points):
        if not edited[index]:
            out.append(point.copy())
            continue
        hit = source.bvh.find_nearest(inverse @ point)
        if hit[0] is None:
            out.append(point.copy())
            continue
        normal = (
            rotation @ design_ops._surface_normal_at(source, hit[0])
        ).normalized()
        gap = (point - (matrix @ hit[0])).dot(normal)
        out.append(point + normal * (offset - gap))
    return out


def _capture_spline(spline):
    """Everything needed to put the curve back bit-exactly."""
    return [
        (
            point.co.copy(),
            point.handle_left.copy(),
            point.handle_right.copy(),
            point.handle_left_type,
            point.handle_right_type,
        )
        for point in spline.bezier_points
    ]


def _restore_spline(spline, state):
    for point, (co, left, right, left_type, right_type) in zip(
        spline.bezier_points, state
    ):
        point.handle_left_type = "FREE"
        point.handle_right_type = "FREE"
        point.co = co
        point.handle_left = left
        point.handle_right = right
        point.handle_left_type = left_type
        point.handle_right_type = right_type


def _arc_chord_ratio(points, run):
    """Arc length over endpoint chord: 1.0 is a straight line.

    This IS the straightening contract, expressed as a number. Straighten's
    job is to make the selected arc read straighter, so this ratio must fall.
    """
    arc = sum(
        (points[run[index + 1]] - points[run[index]]).length
        for index in range(len(run) - 1)
    )
    chord = (points[run[-1]] - points[run[0]]).length
    return arc / chord if chord > 1.0e-12 else math.inf


def _chord_penetration_mm(points, run, scan):
    """How deep the endpoint chord runs INSIDE the body, in mm.

    Reported in the refusal message so the orthotist understands why: an arc
    that wraps the torso has a chord that tunnels through it, and flattening
    onto that chord is not a surface operation at all.
    """
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        from mathutils.bvhtree import BVHTree

        bvh = BVHTree.FromObject(scan, depsgraph)
    except Exception:  # noqa: BLE001
        return 0.0
    inverse = scan.matrix_world.inverted()
    rotation = scan.matrix_world.to_3x3()
    first, last = points[run[0]], points[run[-1]]
    worst = 0.0
    for step in range(21):
        probe = first + (last - first) * (step / 20.0)
        location, normal, _index, _distance = bvh.find_nearest(inverse @ probe)
        if location is None:
            continue
        signed = (probe - (scan.matrix_world @ location)).dot(
            (rotation @ normal).normalized()
        )
        worst = min(worst, signed)
    return -worst * 1000.0


def _keep_trimline_visible(context, curve):
    """Never let an edit leave the edited line undrawn.

    Deliberately narrower than `_set_design_view(context, "TRIM")`, which the
    other trimline mutators call: that also hides every other object, which is
    too blunt for a mid-edit fairing pass. Only the perimeter's own visibility
    is asserted, plus a return from the brace preview, where the perimeter is
    hidden by design and an edit to it would be invisible.
    """
    curve.hide_viewport = False
    try:
        curve.hide_set(False)
    except RuntimeError:
        pass  # not linked into this view layer; nothing to assert
    settings = context.scene.rigo_brace
    if settings.design_view_mode == "BRACE":
        design_ops._set_design_view(context, "TRIM")


# --------------------------------------------------------------------------
# kernels

def _kernel_smooth(dense, weights, sigma_m, iterations):
    count = len(dense)
    working = [point.copy() for point in dense]
    for _pass in range(max(1, iterations)):
        spacing = sum(_spacing(working)) / count
        smoothed = _smooth_closed_parametric(working, sigma_m, spacing)
        working = [
            working[index].lerp(smoothed[index], weights[index])
            for index in range(count)
        ]
    return working


def _kernel_straighten(dense, weights, run, view_direction):
    """Remove the lateral-in-view bow of the arc between its endpoints.

    Only the component perpendicular to the chord WITHIN THE VIEW PLANE is
    flattened; depth (along the view) is untouched here and the subsequent
    depth re-imposition keeps the arc on the body. The result reads straight
    from the chosen view while still wrapping the torso.
    """
    first, last = dense[run[0]], dense[run[-1]]
    chord = last - first
    if chord.length <= 1.0e-9:
        return [point.copy() for point in dense]
    axis = chord.normalized()
    lateral = axis.cross(view_direction)
    if lateral.length <= 1.0e-9:
        lateral = axis.cross(Vector((0.0, 0.0, 1.0)))
    lateral.normalize()
    working = [point.copy() for point in dense]
    for index in run:
        bow = (working[index] - first).dot(lateral)
        working[index] -= lateral * (bow * weights[index])
    return working


# --------------------------------------------------------------------------
# adaptive local refinement (Apply)

def _split_segments(spline, split_after):
    """Exact De Casteljau midpoint split of the listed segments.

    Segment i (control i -> i+1) with Bezier points P0 P1 P2 P3 splits into
    P0 q0 r0 M and M r1 q2 P3, so control i's right handle becomes q0, the
    inserted M carries (r0, r1), and control i+1's left handle becomes q2.
    Shape-preserving by construction (P4): the evaluated curve is unchanged,
    only control capacity is added. Returns (spline, old->new index map,
    inserted new indices) so provenance and manual-handle records survive.
    """
    points = spline.bezier_points
    count = len(points)
    halves = {}
    for index in sorted(split_after):
        first = points[index]
        second = points[(index + 1) % count]
        p0, p1 = first.co.copy(), first.handle_right.copy()
        p2, p3 = second.handle_left.copy(), second.co.copy()
        q0, q1, q2 = (p0 + p1) * 0.5, (p1 + p2) * 0.5, (p2 + p3) * 0.5
        r0, r1 = (q0 + q1) * 0.5, (q1 + q2) * 0.5
        halves[index] = (q0, r0, (r0 + r1) * 0.5, r1, q2)
    states = []
    index_map = {}
    inserted = []
    for index, point in enumerate(points):
        left = point.handle_left.copy()
        right = point.handle_right.copy()
        if (index - 1) % count in halves:
            left = halves[(index - 1) % count][4]
        if index in halves:
            right = halves[index][0]
        index_map[index] = len(states)
        states.append((point.co.copy(), left, right))
        if index in halves:
            _q0, r0, mid, r1, _q2 = halves[index]
            inserted.append(len(states))
            states.append((mid, r0, r1))
    curve = spline.id_data
    curve.splines.remove(spline)
    new_spline = curve.splines.new("BEZIER")
    new_spline.use_cyclic_u = True
    new_spline.bezier_points.add(len(states) - 1)
    for point, (co, left, right) in zip(new_spline.bezier_points, states):
        point.co = co
        point.handle_left_type = "FREE"
        point.handle_right_type = "FREE"
        point.handle_left = left
        point.handle_right = right
    return new_spline, index_map, inserted


def _remap_index_list(values, index_map):
    return sorted(index_map.get(int(v), int(v)) for v in values)


def _nearest_on_path(path, point, hint, window):
    count = len(path)
    best, best_index = math.inf, hint
    for offset in range(-window, window + 1):
        index = (hint + offset) % count
        distance = (path[index] - point).length
        if distance < best:
            best, best_index = distance, index
    return best_index


def _refit_error_m(spline, matrix, path, edited_dense):
    """How far the rebuilt curve strays from the accepted path (edited part)."""
    rebuilt, _per = _dense_path(spline, matrix)
    step = max(1, len(path) // 512)
    worst = 0.0
    ratio = len(rebuilt) / len(path)
    for index in range(0, len(path), step):
        if not edited_dense[index]:
            continue
        hint = int(index * ratio) % len(rebuilt)
        nearest = _nearest_on_path(rebuilt, path[index], hint, 3 * step + 8)
        worst = max(worst, (rebuilt[nearest] - path[index]).length)
    return worst


# --------------------------------------------------------------------------
# the operator

class RIGO_OT_smooth_trimline(Operator):
    """Smooth, straighten or blend the clinical trimline (all sources)"""

    bl_idname = "rigo.smooth_trimline"
    bl_label = "Smooth / Straighten Trimline"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(
        name="Mode",
        items=(
            ("SMOOTH", "Smooth Entire", "Fair the whole trimline"),
            ("SMOOTH_ARC", "Smooth Arc", "Fair only the selected arc"),
            ("STRAIGHTEN", "Straighten Arc (experimental)",
             "EXPERIMENTAL. Make the selected arc read straight from the "
             "current view while still following the body. Verify the brace "
             "generates before accepting the design: on some arcs a "
             "straightened trimline still fails the rim check at Generate "
             "(issue #46, which also affects Smooth Arc)"),
            ("BLEND", "Blend Junction",
             "Fair the transition around the selected point"),
        ),
        default="SMOOTH",
    )
    smoothness: FloatProperty(
        name="Smoothness (mm)",
        description="Physical feature size removed by fairing",
        default=10.0, min=1.0, max=40.0,
    )
    iterations: IntProperty(
        name="Iterations", default=1, min=1, max=8,
        description="Advanced: repeat the fairing pass",
    )
    preserve: FloatProperty(
        name="Preserve Shape", default=0.3, min=0.0, max=0.95,
        description="Blend back toward the original path",
    )
    influence: FloatProperty(
        name="Influence Radius (mm)", default=30.0, min=5.0, max=120.0,
        description="Transition ramp width at arc ends and around the "
                    "blended junction",
    )
    straighten_amount: FloatProperty(
        name="Straighten Amount", default=1.0, min=0.0, max=1.0,
    )
    pin_endpoints: BoolProperty(name="Pin Arc Endpoints", default=True)
    lock_landmarks: BoolProperty(
        name="Lock Semantic Landmarks", default=True,
        description="Opening endpoints and protected stations do not move "
                    "unless they are inside the arc you selected",
    )
    adaptive_refine: BoolProperty(
        name="Refine On Apply", default=False,
        description="Add exact-subdivision controls locally when the measured "
                    "refit error exceeds the tolerance. OFF by default: any "
                    "surface-following path costs ~4 mm of refit error at 42 "
                    "controls (issue #41), so leaving this on would refine on "
                    "every press and immediately exhaust the 168 limit. Turn "
                    "it on deliberately when you want that extra fidelity",
    )
    refine_tolerance: FloatProperty(
        name="Refit Tolerance (mm)", default=5.0, min=0.1, max=10.0,
        description="Refine only when the rebuilt curve strays further than "
                    "this from the accepted path. Depth re-imposition makes "
                    "the accepted path hug the body between stations, and the "
                    "measured cost of carrying that at 42 controls is ~4 mm. "
                    "The default sits ABOVE that floor so ordinary smoothing "
                    "does NOT change the control count; lower it below ~4 mm "
                    "only when you want the extra fidelity and accept the "
                    "denser trimline (issue #41)",
    )
    arc_start: IntProperty(default=-1, options={"HIDDEN"})
    arc_end: IntProperty(default=-1, options={"HIDDEN"})
    view_direction: FloatVectorProperty(
        size=3, default=(0.0, -1.0, 0.0), options={"HIDDEN"},
    )

    # last-run report, drawn in the redo panel
    _report_lines = []

    @classmethod
    def poll(cls, context):
        return (
            bpy.data.objects.get(TRIM_PERIM_NAME) is not None
            and _scan_of(context) is not None
        )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "mode")
        if self.mode == "STRAIGHTEN":
            layout.prop(self, "straighten_amount")
        else:
            layout.prop(self, "smoothness")
            layout.prop(self, "iterations")
        layout.prop(self, "preserve")
        if self.mode != "SMOOTH":
            layout.prop(self, "influence")
            layout.prop(self, "pin_endpoints")
        layout.prop(self, "lock_landmarks")
        row = layout.row()
        row.prop(self, "adaptive_refine")
        row.prop(self, "refine_tolerance", text="Tol")
        for line in self.__class__._report_lines:
            layout.label(text=line)

    # ----------------------------------------------------------------- invoke
    def invoke(self, context, _event):
        curve = bpy.data.objects.get(TRIM_PERIM_NAME)
        spline = curve.data.splines[0]
        selected = [
            index
            for index, point in enumerate(spline.bezier_points)
            if point.select_control_point
        ]
        count = len(spline.bezier_points)
        if self.mode in ("SMOOTH_ARC", "STRAIGHTEN") and len(selected) >= 2:
            # the minimal cyclic run covering the selection
            best = None
            for start in selected:
                for end in selected:
                    run = _cyclic_run(count, start, end)
                    if all(s in run for s in selected):
                        if best is None or len(run) < len(best):
                            best = run
            self.arc_start, self.arc_end = best[0], best[-1]
        elif self.mode == "BLEND" and selected:
            centre = selected[0]
            self.arc_start = (centre - 2) % count
            self.arc_end = (centre + 2) % count
        elif self.mode in ("SMOOTH_ARC", "STRAIGHTEN", "BLEND"):
            self.report(
                {"ERROR"},
                "Select trimline control points first (2+ for an arc, "
                "1 for a junction)",
            )
            return {"CANCELLED"}
        region = getattr(context, "region_data", None)
        if region is not None:
            view = region.view_rotation @ Vector((0.0, 0.0, -1.0))
            self.view_direction = (view.x, view.y, view.z)
        else:
            fx, fy = curve.get("rigo_trim_front", (0.0, -1.0))
            self.view_direction = (fx, fy, 0.0)
        return self.execute(context)

    # ---------------------------------------------------------------- execute
    def execute(self, context):
        curve = bpy.data.objects.get(TRIM_PERIM_NAME)
        scan = _scan_of(context)
        if curve is None or scan is None:
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        spline = curve.data.splines[0]
        matrix = curve.matrix_world
        inverse_curve = matrix.inverted()
        dense, per = _dense_path(spline, matrix)
        count = len(dense)
        n_ctrl = len(spline.bezier_points)
        # Straighten is the one mode that can fail its own contract, so it
        # carries a rollback snapshot. Taken before any mutation.
        rollback = (
            _capture_spline(spline) if self.mode == "STRAIGHTEN" else None
        )
        arc_run_controls = (
            _cyclic_run(n_ctrl, self.arc_start % n_ctrl, self.arc_end % n_ctrl)
            if self.mode == "STRAIGHTEN" and self.arc_start >= 0
            else None
        )
        ratio_before = (
            _arc_chord_ratio(
                [matrix @ p.co for p in spline.bezier_points], arc_run_controls
            )
            if arc_run_controls
            else None
        )

        # ---- window
        if self.mode == "SMOOTH" or self.arc_start < 0:
            run = list(range(count))
            weights = [1.0] * count
        else:
            run = _cyclic_run(
                count, (self.arc_start * per) % count,
                (self.arc_end * per) % count,
            )
            weights = _ramp_weights(
                dense, run, self.influence * 0.001, self.pin_endpoints
            )
        if self.lock_landmarks:
            protected = _opening_locked_indices(
                curve, [matrix @ p.co for p in spline.bezier_points]
            )
            # a landmark INSIDE the user's explicit arc selection is the
            # user's to move; landmarks outside it are locked (owner policy)
            outside = [
                c * per for c in protected
                if self.mode == "SMOOTH" or (c * per) not in run[1:-1]
            ]
            weights = _landmark_zero_zones(
                dense, weights, outside, max(0.010, self.smoothness * 0.001)
            )

        # ---- kernel
        if self.mode == "STRAIGHTEN":
            scaled = [w * self.straighten_amount for w in weights]
            processed = _kernel_straighten(
                dense, scaled, run, Vector(self.view_direction).normalized()
            )
        else:
            processed = _kernel_smooth(
                dense, weights, self.smoothness * 0.001, self.iterations
            )

        # ---- preserve blend + full-depth re-imposition on edited samples
        processed = [
            dense[i].lerp(processed[i], 1.0 - self.preserve)
            for i in range(count)
        ]
        edited = [
            (processed[i] - dense[i]).length > 1.0e-9 for i in range(count)
        ]
        source, inverse, m, rotation = _surface_context(scan)
        processed = _redepth(
            processed, edited, source, inverse, m, rotation, SURFACE_OFFSET
        )

        # ---- write stations of the edited run, banded C2 re-solve
        touched_controls = sorted(
            {i for i in range(n_ctrl) if edited[(i * per) % count]}
        )
        for index in touched_controls:
            point = spline.bezier_points[index]
            point.co = inverse_curve @ processed[(index * per) % count]
        if touched_controls:
            if self.mode == "SMOOTH":
                _set_c2_tangent_handles(spline)
                curve["rigo_trim_handle_model"] = "C2_PERIODIC"
            else:
                band_run = _cyclic_run(
                    n_ctrl,
                    (touched_controls[0] - 1) % n_ctrl,
                    (touched_controls[-1] + 1) % n_ctrl,
                )
                solve_band_c2(
                    spline, band_run, manual=manual_handle_indices(curve)
                )
                curve["rigo_trim_handle_model"] = "C2_BANDED"

        # ---- Straighten must satisfy its own contract or not happen at all
        #
        # `_kernel_straighten` removes the arc's lateral bow toward the CHORD
        # between its pinned endpoints. That is only a surface operation while
        # the chord stays near the body. For an arc that wraps the torso the
        # chord tunnels straight through it - measured 210.7 mm long with 9 of
        # 11 samples inside the body, worst -98.6 mm - so flattening drags the
        # path inside and the depth re-imposition then re-projects each sample
        # onto whatever surface is nearest, which moved one control 105.15 mm
        # to a completely different part of the body. Adherence still reads a
        # perfect +1.500 mm afterwards, so no surface-distance check can catch
        # it; the brace then fails to build with non-manifold rim edges.
        #
        # The discriminator is the contract itself: Straighten's job is to make
        # the arc read straighter, and arc/chord ratio is that statement as a
        # number. Measured over seven arcs, the ratio rose in exactly one - the
        # catastrophic one (1.9841 -> 2.1780) - and fell in every arc that
        # built. So a ratio that does not fall means the operation failed, and
        # the trimline is restored bit-exactly rather than left in an
        # apparently accepted state that only fails later at Generate.
        if rollback is not None and ratio_before is not None:
            ratio_after = _arc_chord_ratio(
                [matrix @ p.co for p in spline.bezier_points], arc_run_controls
            )
            if ratio_after > ratio_before * (1.0 + 1.0e-6):
                _restore_spline(spline, rollback)
                curve.data.update_tag()
                _keep_trimline_visible(context, curve)
                penetration = _chord_penetration_mm(
                    [matrix @ p.co for p in spline.bezier_points],
                    arc_run_controls,
                    scan,
                )
                self.report(
                    {"ERROR"},
                    "Straighten cannot flatten this arc: it wraps the body, so "
                    f"the straight line between its ends runs {penetration:.0f} "
                    "mm inside the torso and the arc would get less straight "
                    f"({ratio_before:.3f} -> {ratio_after:.3f}), not more. The "
                    "trimline is unchanged. Select a shorter arc that faces "
                    "you in the current view.",
                )
                return {"CANCELLED"}

        # ---- adaptive local refinement, gated on MEASURED refit error
        refined_added = 0
        error_m = _refit_error_m(spline, matrix, processed, edited)
        if self.adaptive_refine:
            rounds = 0
            while (
                error_m > self.refine_tolerance * 0.001
                and len(spline.bezier_points) < _MAX_CONTROLS
                and rounds < _REFINE_ROUNDS
            ):
                rounds += 1
                spline, error_m, added = self._refine_round(
                    curve, spline, matrix, inverse_curve, processed,
                    edited, per,
                )
                refined_added += added
                if added == 0:
                    break
        mark_handles_solved(curve)
        curve.data.update_tag()
        mark_brace_dirty(context, "Trimline smoothed/straightened")
        _keep_trimline_visible(context, curve)

        self.__class__._report_lines = [
            f"refit error {error_m*1000:.2f} mm "
            f"(tolerance {self.refine_tolerance:.2f})",
            f"controls: {len(spline.bezier_points)} "
            f"(+{refined_added} refined)" if refined_added else
            f"controls: {len(spline.bezier_points)} (no refinement needed)",
        ]
        self.report(
            {"INFO"},
            f"{self.mode.title().replace('_', ' ')}: refit error "
            f"{error_m*1000:.2f} mm, +{refined_added} controls",
        )
        return {"FINISHED"}

    def _refine_round(
        self, curve, spline, matrix, inverse_curve, path, edited, per
    ):
        """Split the worst offending EDITED segments, exactly, then re-fit."""
        n_ctrl = len(spline.bezier_points)
        rebuilt, _p = _dense_path(spline, matrix)
        ratio = len(rebuilt) / len(path)
        segment_error = {}
        step = max(1, len(path) // 512)
        for index in range(0, len(path), step):
            if not edited[index]:
                continue
            hint = int(index * ratio) % len(rebuilt)
            nearest = _nearest_on_path(rebuilt, path[index], hint, 3 * step + 8)
            seg = min(n_ctrl - 1, nearest // max(1, len(rebuilt) // n_ctrl))
            err = (rebuilt[nearest] - path[index]).length
            segment_error[seg] = max(segment_error.get(seg, 0.0), err)
        budget = _MAX_CONTROLS - n_ctrl
        offenders = sorted(
            (s for s, e in segment_error.items()
             if e > self.refine_tolerance * 0.001),
            key=lambda s: -segment_error[s],
        )[:budget]
        if not offenders:
            return spline, _refit_error_m(spline, matrix, path, edited), 0
        spline, index_map, inserted = _split_segments(
            spline, {s: True for s in offenders}
        )
        # provenance + manual-handle records survive the renumbering
        curve[REFINED_CONTROLS_KEY] = _remap_index_list(
            list(curve.get(REFINED_CONTROLS_KEY, [])), index_map
        ) + inserted
        if curve.get(MANUAL_HANDLE_KEY):
            curve[MANUAL_HANDLE_KEY] = _remap_index_list(
                list(curve[MANUAL_HANDLE_KEY]), index_map
            )
        # move the new stations onto the accepted path and re-solve locally
        new_per = max(24, _DENSE_TOTAL // len(spline.bezier_points))
        for new_index in inserted:
            point = spline.bezier_points[new_index]
            world = matrix @ point.co
            hint = min(
                range(0, len(path), 4),
                key=lambda i: (path[i] - world).length,
            )
            target = path[_nearest_on_path(path, world, hint, 8)]
            delta = (inverse_curve @ target) - point.co
            point.co += delta
            point.handle_left += delta
            point.handle_right += delta
        touched = sorted(inserted)
        band_run = _cyclic_run(
            len(spline.bezier_points),
            (touched[0] - 2) % len(spline.bezier_points),
            (touched[-1] + 2) % len(spline.bezier_points),
        )
        if len(band_run) >= len(spline.bezier_points) - 2:
            _set_c2_tangent_handles(spline)
        else:
            solve_band_c2(spline, band_run,
                          manual=manual_handle_indices(curve))
        return (
            spline,
            _refit_error_m(spline, matrix, path, edited),
            len(inserted),
        )


_CLASSES = (RIGO_OT_smooth_trimline,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
