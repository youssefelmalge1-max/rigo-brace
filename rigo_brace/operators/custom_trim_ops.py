"""Painted custom trimline extraction for spinal-brace design.

The green/white POINT color-mask interaction is learned from uFit 2.2.2
(GPL-3.0, Ugani Prosthetics; provenance PROV-0014).  Boundary extraction,
surface-constrained fairing, clinical validation, and integration with the Rigo
perimeter/shell pipeline are original brace-specific implementations.
"""

import math
from collections import defaultdict
from dataclasses import dataclass

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

from ..core import mark_brace_dirty
from .trimline_ops import (
    SURFACE_OFFSET,
    TRIM_BOT_NAME,
    TRIM_PERIM_NAME,
    TRIM_TOP_NAME,
    _anchors,
    _constrain_perimeter,
    _make_trim_curve,
    _scan_of,
)

CUSTOM_MASK_NAME = "RIGO_CUSTOM_TRIM_MASK"
_MASK_WHITE = (1.0, 1.0, 1.0, 1.0)
_MASK_GREEN = (0.0, 1.0, 0.0, 1.0)
_MASK_THRESHOLD = 0.5
_MIN_BOUNDARY_LENGTH_M = 0.20
_MIN_BOUNDARY_HEIGHT_M = 0.05
_MIN_ANGULAR_COVERAGE = math.radians(180.0)
# Density ceiling. Raising it to 168/240 makes the perimeter more faithful but
# `_validate_finished_rim` then cancels with 1/5 "local rim overlap(s)".
# Measured (tools/rimoverlapdbg.py) - the overlaps are NOT in the rim fillet and
# NOT in the outer wall (its collision repair reports zero at every density):
# they are INNER wall against INNER wall, i.e. the patient-contact surface
# folding into itself. A denser trimline follows the paint more closely and so
# retains ~26 % more of the offset mold (16739 -> 21111 vertices), including
# concave pockets where the offset surface already self-intersects. Neither the
# rim-radius clamp nor the trimline curvature limit changes it (both measured,
# both no-ops here). Fixing it means fixing the offset mold, which is a separate
# defect from the trimline. Until then a ~2 m perimeter carries ~24 mm control
# spacing, and `rigo_trim_smoothing_deviation_mm` is measured on the DELIVERED
# curve so the limit is visible to the orthotist rather than hidden.
_MAX_CUSTOM_CONTROLS = 84
# Arc-length spacing of the dense loop the parametric smoother runs on. Fixed,
# so the smoothing result depends only on the requested millimetres and never
# on scan resolution or on how the orthotist painted.
_SMOOTH_SAMPLE_M = 0.001
# Bounded, fixed-step corner relaxation. These are internal convergence limits,
# never user-facing knobs: the orthotist sets a radius in millimetres.
_CURVATURE_PASSES = 400
_CURVATURE_RELAX = 0.5


class CustomTrimMaskError(RuntimeError):
    """The painted mask cannot define one safe brace perimeter."""


@dataclass(frozen=True)
class _MaskContour:
    coordinates: tuple
    length_m: float
    angular_coverage: float
    smoothing_passes: int
    smoothing_mm: float = 0.0
    smoothing_deviation_mm: float = 0.0
    requested_min_radius_mm: float = 0.0
    achieved_min_radius_mm: float = 0.0


def _ensure_mask(scan):
    mesh = scan.data
    attribute = mesh.color_attributes.get(CUSTOM_MASK_NAME)
    if attribute is None or attribute.domain != "POINT":
        if attribute is not None:
            mesh.color_attributes.remove(attribute)
        attribute = mesh.color_attributes.new(
            name=CUSTOM_MASK_NAME,
            type="FLOAT_COLOR",
            domain="POINT",
        )
        for item in attribute.data:
            item.color = _MASK_WHITE
    for index, candidate in enumerate(mesh.color_attributes):
        if candidate == attribute:
            mesh.attributes.active_color_index = index
            break
    return attribute


def _mask_value(color):
    # White is the only excluded state.  Treat green (the intended brush
    # color) and any darker legacy stroke as selected, so a Blender brush
    # asset overriding the visible RGB cannot silently discard user work.
    return max(0.0, min(1.0, 1.0 - 0.5 * (color[0] + color[2])))


def _mask_values(scan):
    attribute = scan.data.color_attributes.get(CUSTOM_MASK_NAME)
    if attribute is None or len(attribute.data) != len(scan.data.vertices):
        raise CustomTrimMaskError("Paint the custom brace area first")
    return [_mask_value(item.color) for item in attribute.data]


def _write_mask_values(scan, values):
    attribute = _ensure_mask(scan)
    for item, value in zip(attribute.data, values):
        clamped = max(0.0, min(1.0, value))
        item.color = (1.0 - clamped, 1.0, 1.0 - clamped, 1.0)
    scan.data.update()


def _vertex_neighbours(mesh):
    neighbours = [set() for _vertex in mesh.vertices]
    for edge in mesh.edges:
        first, second = edge.vertices
        neighbours[first].add(second)
        neighbours[second].add(first)
    return neighbours


def _smooth_mask_once(mask_values, neighbours):
    smoothed_values = []
    for index, mask_value in enumerate(mask_values):
        ring_values = [mask_values[neighbour] for neighbour in neighbours[index]]
        if not ring_values:
            smoothed_values.append(mask_value)
            continue
        ring_average = sum(ring_values) / len(ring_values)
        smoothed_values.append(mask_value * 0.35 + ring_average * 0.65)
    return smoothed_values


def _adjust_mask_values(mesh, values, action, steps):
    if action == "CLEAR":
        return [0.0] * len(values)
    if action == "INVERT":
        return [1.0 - value for value in values]
    neighbours = _vertex_neighbours(mesh)
    adjusted = list(values)
    for _step in range(steps):
        previous = adjusted
        if action == "SMOOTH":
            adjusted = _smooth_mask_once(previous, neighbours)
            continue
        adjusted = []
        for index, value in enumerate(previous):
            ring = [previous[neighbour] for neighbour in neighbours[index]]
            if not ring:
                adjusted.append(value)
            elif action == "GROW":
                adjusted.append(max([value, *ring]))
            elif action == "SHRINK":
                adjusted.append(min([value, *ring]))
    return adjusted


def _edge_crossing(mesh, values, first, second):
    first_value = values[first]
    second_value = values[second]
    if (first_value >= _MASK_THRESHOLD) == (second_value >= _MASK_THRESHOLD):
        return None
    fraction = (_MASK_THRESHOLD - first_value) / (second_value - first_value)
    coordinate = mesh.vertices[first].co.lerp(mesh.vertices[second].co, fraction)
    return tuple(sorted((first, second))), coordinate


def _marching_mask_graph(mesh, values):
    mesh.calc_loop_triangles()
    coordinates = {}
    adjacency = defaultdict(set)
    for triangle in mesh.loop_triangles:
        vertices = tuple(triangle.vertices)
        crossings = []
        for first, second in (
            (vertices[0], vertices[1]),
            (vertices[1], vertices[2]),
            (vertices[2], vertices[0]),
        ):
            crossing = _edge_crossing(mesh, values, first, second)
            if crossing is not None:
                crossings.append(crossing)
        if len(crossings) != 2:
            continue
        first_key, first_coordinate = crossings[0]
        second_key, second_coordinate = crossings[1]
        if first_key == second_key:
            continue
        coordinates[first_key] = first_coordinate
        coordinates[second_key] = second_coordinate
        adjacency[first_key].add(second_key)
        adjacency[second_key].add(first_key)
    return coordinates, adjacency


def _ordered_closed_loops(coordinates, adjacency):
    invalid = [key for key, neighbours in adjacency.items() if len(neighbours) != 2]
    if invalid:
        raise CustomTrimMaskError(
            "Painted boundary branches or touches itself; smooth or repaint that area"
        )
    loops = []
    unvisited = set(adjacency)
    while unvisited:
        start = min(unvisited)
        ordered = [start]
        previous = None
        current = start
        while True:
            following = next(
                neighbour
                for neighbour in adjacency[current]
                if neighbour != previous
            )
            if following == start:
                break
            if following in ordered:
                raise CustomTrimMaskError("Painted boundary crosses itself")
            ordered.append(following)
            previous, current = current, following
        unvisited.difference_update(ordered)
        loops.append(tuple(coordinates[key].copy() for key in ordered))
    return loops


def _mask_loops(mesh, mask_values):
    coordinates, adjacency = _marching_mask_graph(mesh, mask_values)
    return _ordered_closed_loops(coordinates, adjacency)


def _topology_preserving_mask_loop(mesh, mask_values, maximum_steps):
    """Stop smoothing before a narrow painted opening collapses."""
    neighbours = _vertex_neighbours(mesh)
    smoothed_values = list(mask_values)
    last_loop = None
    used_steps = 0
    for step in range(max(0, int(maximum_steps)) + 1):
        if step:
            smoothed_values = _smooth_mask_once(smoothed_values, neighbours)
        loops = _mask_loops(mesh, smoothed_values)
        if len(loops) != 1:
            if last_loop is not None:
                break
            raise CustomTrimMaskError(
                "Paint one continuous brace perimeter; "
                f"the unsmoothed mask has {len(loops)} boundaries"
            )
        last_loop = loops[0]
        used_steps = step
    return last_loop, used_steps


def _closed_length(coordinates):
    return sum(
        (coordinate - coordinates[index - 1]).length
        for index, coordinate in enumerate(coordinates)
    )


def _resample_closed_count(coordinates, count):
    """Resample a closed polyline to `count` points evenly spaced by arc length."""
    if len(coordinates) < 3:
        raise CustomTrimMaskError("Painted boundary has too few points")
    cumulative = [0.0]
    for index in range(len(coordinates)):
        following = (index + 1) % len(coordinates)
        cumulative.append(
            cumulative[-1] + (coordinates[following] - coordinates[index]).length
        )
    total = cumulative[-1]
    result = []
    segment = 0
    for sample_index in range(count):
        distance = total * sample_index / count
        while segment + 1 < len(cumulative) and cumulative[segment + 1] < distance:
            segment += 1
        segment_length = cumulative[segment + 1] - cumulative[segment]
        fraction = (distance - cumulative[segment]) / max(segment_length, 1.0e-12)
        following = (segment + 1) % len(coordinates)
        result.append(coordinates[segment].lerp(coordinates[following], fraction))
    return result


def _resample_closed(coordinates, spacing_m):
    total = _closed_length(coordinates)
    count = max(24, min(_MAX_CUSTOM_CONTROLS, round(total / spacing_m)))
    return _resample_closed_count(coordinates, count)


def _gaussian_ring_weights(sigma_samples, radius):
    weights = [
        math.exp(-0.5 * (offset / sigma_samples) ** 2)
        for offset in range(-radius, radius + 1)
    ]
    total = sum(weights)
    return [weight / total for weight in weights]


def _smooth_closed_parametric(coordinates, sigma_m, spacing_m):
    """Remove boundary detail below one physical size, in a single pass.

    A Gaussian convolution along arc length: the orthotist sets one millimetre
    value and the result is closed-form and order-independent — no iteration
    count, and no dependence on scan density (the input is resampled to a fixed
    arc-length spacing first). Bounded feature size, not a number of passes, is
    what the clinical control has to mean.
    """
    count = len(coordinates)
    if sigma_m <= 0.0 or count < 8:
        return list(coordinates)
    sigma_samples = sigma_m / spacing_m
    if sigma_samples < 0.5:
        return list(coordinates)
    radius = min(max(1, math.ceil(3.0 * sigma_samples)), (count - 1) // 2)
    weights = _gaussian_ring_weights(sigma_samples, radius)
    smoothed = []
    for index in range(count):
        accumulated = Vector((0.0, 0.0, 0.0))
        for step, weight in enumerate(weights):
            offset = step - radius
            accumulated += coordinates[(index + offset) % count] * weight
        smoothed.append(accumulated)
    return smoothed


def _turn_radius_m(previous, current, following):
    """Circumradius of three consecutive samples: the local turn radius."""
    first = (current - previous).length
    second = (following - current).length
    third = (following - previous).length
    if min(first, second, third) <= 1.0e-12:
        return math.inf
    half = (first + second + third) * 0.5
    area_squared = max(
        half * (half - first) * (half - second) * (half - third), 0.0
    )
    if area_squared <= 1.0e-24:
        return math.inf
    return (first * second * third) / (4.0 * math.sqrt(area_squared))


def _minimum_turn_radius_m(coordinates):
    count = len(coordinates)
    if count < 3:
        return math.inf
    return min(
        _turn_radius_m(
            coordinates[index - 1],
            coordinates[index],
            coordinates[(index + 1) % count],
        )
        for index in range(count)
    )


def _clamp_closed_curvature(coordinates, minimum_radius_m):
    """Widen the corners that turn tighter than the requested radius.

    Smoothing bounds feature SIZE, not turn RADIUS: an unsmoothed 15 mm wobble
    5 mm deep leaves a 1.2 mm corner, which is a stress riser in the printed rim
    and a pressure point on skin.

    This is a BEST EFFORT, not a guarantee. Local relaxation reaches the target
    when the deficit is mild (measured 7.99 -> 10.00 mm for a 10 mm request),
    but on a deep narrow notch it improves without converging (0.43 -> 2.32 mm
    for a 5 mm request) - genuinely honouring that would have to move the
    trimline far enough to change the prescription. The achieved radius is
    therefore measured and reported, and the caller warns when it falls short.

    The relaxation is local, bounded and fixed-step, so the result depends only
    on the requested millimetres - the orthotist never sees an iteration count.
    """
    count = len(coordinates)
    if minimum_radius_m <= 0.0 or count < 8:
        return list(coordinates), _minimum_turn_radius_m(coordinates)
    points = list(coordinates)
    for _pass in range(_CURVATURE_PASSES):
        tight = [
            index
            for index in range(count)
            if _turn_radius_m(
                points[index - 1], points[index], points[(index + 1) % count]
            )
            < minimum_radius_m
        ]
        if not tight:
            break
        relaxed = list(points)
        for index in tight:
            midpoint = (
                points[index - 1] + points[(index + 1) % count]
            ) * 0.5
            relaxed[index] = points[index].lerp(midpoint, _CURVATURE_RELAX)
        points = relaxed
    return points, _minimum_turn_radius_m(points)


def _maximum_deviation_m(smoothed, reference, window):
    """Largest distance from the smoothed loop back to the painted boundary.

    Reported to the orthotist so the smoothing cannot silently walk the trimline
    away from the painted intent. Both loops carry the same arc-length
    parameterization and a Gaussian window cannot move a point further along the
    loop than its own radius, so the nearest painted point is searched within
    that radius instead of over the whole loop.
    """
    count = len(reference)
    span = min(window, count // 2)
    return max(
        min(
            (point - reference[(index + offset) % count]).length
            for offset in range(-span, span + 1)
        )
        for index, point in enumerate(smoothed)
    )


def _nearest_surface_world(scan, bvh, coordinate):
    inverse = scan.matrix_world.inverted()
    hit = bvh.find_nearest(inverse @ coordinate)
    if hit[0] is None:
        return None
    normal_matrix = inverse.transposed().to_3x3()
    normal = (normal_matrix @ hit[1]).normalized()
    return scan.matrix_world @ hit[0] + normal * SURFACE_OFFSET


def _fair_surface_loop(scan, coordinates, iterations=18):
    bvh = BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())
    fair = list(coordinates)
    for _iteration in range(iterations):
        previous = list(fair)
        segment_lengths = [
            (coordinate - previous[index - 1]).length
            for index, coordinate in enumerate(previous)
        ]
        typical_step = sorted(segment_lengths)[len(segment_lengths) // 2]
        maximum_step = max(0.00015, min(0.00075, typical_step * 0.20))
        for index, coordinate in enumerate(previous):
            target = (previous[index - 1] + previous[(index + 1) % len(previous)]) * 0.5
            displacement = (target - coordinate) * 0.55
            if displacement.length > maximum_step:
                displacement.length = maximum_step
            fitted = _nearest_surface_world(scan, bvh, coordinate + displacement)
            if fitted is not None:
                fair[index] = fitted
    return fair


def _angular_coverage(coordinates, axis, front):
    angles = []
    for coordinate in coordinates:
        relative_x = coordinate.x - axis.x
        relative_y = coordinate.y - axis.y
        angles.append(
            math.atan2(
                relative_x * (-front.y) + relative_y * front.x,
                relative_x * front.x + relative_y * front.y,
            )
            % math.tau
        )
    angles.sort()
    gaps = [
        (angles[(index + 1) % len(angles)] - angle) % math.tau
        for index, angle in enumerate(angles)
    ]
    return math.tau - max(gaps)


def _reviewed_mask_loop(scan):
    values = _mask_values(scan)
    if max(values, default=0.0) < 0.55:
        raise CustomTrimMaskError("No green brace area is painted")
    if min(values, default=1.0) > 0.45:
        raise CustomTrimMaskError("The whole scan is painted; leave the outside area white")
    loops = _mask_loops(scan.data, values)
    if len(loops) != 1:
        raise CustomTrimMaskError(
            "Paint exactly one connected brace area; "
            f"the reviewed mask has {len(loops)} boundaries"
        )
    return loops[0]


def _fit_reviewed_boundary(context, scan, world_loop, spacing_m):
    resampled = _resample_closed(world_loop, spacing_m)
    bvh = BVHTree.FromObject(scan, context.evaluated_depsgraph_get())
    fitted = [
        fitted
        for coordinate in resampled
        if (fitted := _nearest_surface_world(scan, bvh, coordinate)) is not None
    ]
    if len(fitted) < 24:
        raise CustomTrimMaskError("Could not fit the painted boundary to the body")
    return fitted


def _validate_custom_contour(context, scan, fitted):
    _bottom, _waist, _top, axis, front, _warnings = _anchors(context, scan)
    height = max(point.z for point in fitted) - min(point.z for point in fitted)
    coverage = _angular_coverage(fitted, axis, front)
    if height < _MIN_BOUNDARY_HEIGHT_M:
        raise CustomTrimMaskError("Painted brace area is too short vertically")
    if coverage < _MIN_ANGULAR_COVERAGE:
        raise CustomTrimMaskError(
            "Painted area does not wrap far enough around the torso"
        )
    return coverage


def _smoothed_painted_boundary(world_loop, length_m, smoothing_m):
    """(loop to fit, deviation from the painted line in m). One pass, no
    iteration count: `smoothing_m` alone determines the result."""
    if smoothing_m <= 0.0:
        return world_loop, 0.0
    dense_count = max(24, round(length_m / _SMOOTH_SAMPLE_M))
    dense = _resample_closed_count(world_loop, dense_count)
    smoothed = _smooth_closed_parametric(dense, smoothing_m, _SMOOTH_SAMPLE_M)
    window = math.ceil(3.0 * smoothing_m / _SMOOTH_SAMPLE_M) + 2
    return smoothed, _maximum_deviation_m(smoothed, dense, window)


def _control_spacing_m(spacing_m, smoothing_m):
    """Control spacing fine enough to actually carry the requested smoothing.

    Two samples per sigma: a curve decimated more coarsely than the filter
    cannot represent what the filter produced, and the leftover decimation
    error would masquerade as smoothing.
    """
    if smoothing_m <= 0.0:
        return spacing_m
    return min(spacing_m, smoothing_m * 0.5)


def _delivered_deviation_m(context, scan, fitted, dense):
    """How far the DELIVERED curve sits from the painted boundary.

    Measured after smoothing, decimation and surface refitting, against the
    painted line carried onto the same offset surface — so the reported
    millimetres are the ones the shell is actually cut with, not the smoother's
    internal intermediate.
    """
    bvh = BVHTree.FromObject(scan, context.evaluated_depsgraph_get())
    reference = [
        point
        for coordinate in dense
        if (point := _nearest_surface_world(scan, bvh, coordinate)) is not None
    ]
    if not reference or not fitted:
        return 0.0
    tree = KDTree(len(reference))
    for index, point in enumerate(reference):
        tree.insert(point, index)
    tree.balance()
    return max(tree.find(point)[2] for point in fitted)


def _extract_custom_contour(
    context, scan, spacing_m, smoothing_m, minimum_radius_m
):
    loop = _reviewed_mask_loop(scan)
    world_loop = [scan.matrix_world @ coordinate for coordinate in loop]
    length_m = _closed_length(world_loop)
    if length_m < _MIN_BOUNDARY_LENGTH_M:
        raise CustomTrimMaskError("Painted brace boundary is too small")
    dense = _resample_closed_count(
        world_loop, max(24, round(length_m / _SMOOTH_SAMPLE_M))
    )
    shaped, _internal = _smoothed_painted_boundary(
        world_loop, length_m, smoothing_m
    )
    shaped, _dense_radius = _clamp_closed_curvature(shaped, minimum_radius_m)
    fitted = _fit_reviewed_boundary(
        context, scan, shaped, _control_spacing_m(spacing_m, smoothing_m)
    )
    coverage = _validate_custom_contour(context, scan, fitted)
    deviation_m = _delivered_deviation_m(context, scan, fitted, dense)
    # Measured on the DELIVERED controls, so the reported radius is the one the
    # shell is actually cut with.
    achieved_radius_m = _minimum_turn_radius_m(fitted)
    return _MaskContour(
        tuple(fitted),
        length_m,
        coverage,
        0,
        smoothing_m * 1000.0,
        deviation_m * 1000.0,
        minimum_radius_m * 1000.0,
        achieved_radius_m * 1000.0,
    )


def _delete_curve(name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        return
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data.users == 0:
        bpy.data.curves.remove(data)


def _activate_mask_paint(context, scan):
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    scan.hide_set(False)
    scan.select_set(True)
    context.view_layer.objects.active = scan
    _ensure_mask(scan)
    bpy.ops.object.mode_set(mode="VERTEX_PAINT")
    try:
        bpy.ops.wm.tool_set_by_id(name="builtin_brush.Draw")
    except RuntimeError:
        pass
    paint_settings = context.tool_settings.vertex_paint
    brush = paint_settings.brush
    if brush is not None:
        brush.color = _MASK_GREEN[:3]
        brush.secondary_color = _MASK_WHITE[:3]
        brush.size = 50
        brush.strength = 1.0
    unified = paint_settings.unified_paint_settings
    unified.use_unified_color = True
    unified.use_unified_size = True
    unified.use_unified_strength = True
    unified.color = _MASK_GREEN[:3]
    unified.secondary_color = _MASK_WHITE[:3]
    unified.size = 50
    unified.strength = 1.0
    for area in context.screen.areas:
        if area.type == "VIEW_3D":
            area.spaces.active.shading.color_type = "VERTEX"


class RIGO_OT_custom_trim_paint(Operator):
    """Paint the wanted brace area green on the corrected body."""

    bl_idname = "rigo.custom_trim_paint"
    bl_label = "Paint Brace Area"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return _scan_of(context) is not None

    def execute(self, context):
        scan = _scan_of(context)
        _activate_mask_paint(context, scan)
        self.report(
            {"INFO"},
            "Paint green to keep; Ctrl uses white to erase; rotate to paint every side",
        )
        return {"FINISHED"}


class RIGO_OT_custom_trim_mask_adjust(Operator):
    """Grow, shrink, smooth, invert, or clear the custom green mask."""

    bl_idname = "rigo.custom_trim_mask_adjust"
    bl_label = "Adjust Custom Trim Mask"
    bl_options = {"REGISTER", "UNDO"}

    action: EnumProperty(
        items=(
            ("GROW", "Grow", "Expand the green mask"),
            ("SHRINK", "Shrink", "Contract the green mask"),
            ("SMOOTH", "Smooth", "Feather and regularize the mask boundary"),
            ("INVERT", "Invert", "Swap kept and excluded areas"),
            ("CLEAR", "Clear", "Remove the complete custom mask"),
        ),
        default="SMOOTH",
    )

    @classmethod
    def poll(cls, context):
        return _scan_of(context) is not None

    def execute(self, context):
        scan = _scan_of(context)
        settings = context.scene.rigo_brace
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        try:
            values = _mask_values(scan)
        except CustomTrimMaskError as error:
            if self.action != "CLEAR":
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            _ensure_mask(scan)
            values = [0.0] * len(scan.data.vertices)
        steps = (
            settings.trim_mask_smooth
            if self.action == "SMOOTH"
            else settings.trim_mask_steps
        )
        adjusted = _adjust_mask_values(scan.data, values, self.action, steps)
        _write_mask_values(scan, adjusted)
        _activate_mask_paint(context, scan)
        self.report({"INFO"}, f"Custom trim mask: {self.action.lower()}")
        return {"FINISHED"}


class RIGO_OT_custom_trim_from_paint(Operator):
    """Extract one smooth, surface-bound perimeter from the green mask."""

    bl_idname = "rigo.custom_trim_from_paint"
    bl_label = "Create Trimline from Paint"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _scan_of(context) is not None

    def execute(self, context):
        scan = _scan_of(context)
        settings = context.scene.rigo_brace
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        try:
            contour = _extract_custom_contour(
                context,
                scan,
                settings.trim_custom_spacing * 0.001,
                settings.trim_smooth_mm * 0.001,
                settings.trim_min_radius_mm * 0.001,
            )
        except CustomTrimMaskError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        for name in (TRIM_TOP_NAME, TRIM_BOT_NAME, TRIM_PERIM_NAME):
            _delete_curve(name)
        perimeter = _make_trim_curve(
            context,
            TRIM_PERIM_NAME,
            contour.coordinates,
            (1.0, 0.55, 0.05, 1.0),
        )
        _constrain_perimeter(perimeter, scan)
        _bottom, _waist, _top, axis, front, warnings = _anchors(context, scan)
        perimeter["rigo_trim_axis"] = (axis.x, axis.y)
        perimeter["rigo_trim_front"] = (front.x, front.y)
        perimeter["rigo_trim_type"] = "CUSTOM_PAINT"
        perimeter["rigo_trim_source"] = "CUSTOM_PAINT"
        perimeter["rigo_trim_mask_attribute"] = CUSTOM_MASK_NAME
        perimeter["rigo_trim_boundary_length_mm"] = contour.length_m * 1000.0
        perimeter["rigo_trim_angular_coverage_deg"] = math.degrees(
            contour.angular_coverage
        )
        perimeter["rigo_trim_mask_smoothing_passes"] = contour.smoothing_passes
        perimeter["rigo_trim_smoothing_mm"] = contour.smoothing_mm
        perimeter["rigo_trim_smoothing_deviation_mm"] = (
            contour.smoothing_deviation_mm
        )
        perimeter["rigo_trim_min_radius_requested_mm"] = (
            contour.requested_min_radius_mm
        )
        perimeter["rigo_trim_min_radius_mm"] = contour.achieved_min_radius_mm
        perimeter["requires_orthotist_review"] = True
        mark_brace_dirty(context, "Custom painted trim perimeter created")
        from .design_ops import _set_design_view

        _set_design_view(context, "TRIM")
        for warning in warnings:
            self.report({"WARNING"}, warning)
        if contour.smoothing_mm > 0.0:
            detail = (
                f"smoothed {contour.smoothing_mm:.1f} mm in one pass, "
                f"moved at most {contour.smoothing_deviation_mm:.1f} mm "
                "from the painted line"
            )
        else:
            detail = "painted line kept exactly (smoothing 0 mm)"
        if contour.requested_min_radius_mm > 0.0:
            detail += (
                f"; tightest corner {contour.achieved_min_radius_mm:.1f} mm "
                f"(limit {contour.requested_min_radius_mm:.1f} mm)"
            )
            if contour.achieved_min_radius_mm < contour.requested_min_radius_mm:
                self.report(
                    {"WARNING"},
                    "Trimline still turns tighter than the requested minimum "
                    f"radius: {contour.achieved_min_radius_mm:.1f} mm against "
                    f"{contour.requested_min_radius_mm:.1f} mm. Raise Trimline "
                    "Smoothing or repaint that corner wider.",
                )
        self.report(
            {"INFO"},
            f"Custom trimline: {len(contour.coordinates)} controls, "
            f"{contour.length_m * 1000.0:.0f} mm boundary; {detail}",
        )
        return {"FINISHED"}


_CLASSES = (
    RIGO_OT_custom_trim_paint,
    RIGO_OT_custom_trim_mask_adjust,
    RIGO_OT_custom_trim_from_paint,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
