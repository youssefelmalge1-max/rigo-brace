"""Installed-copy acceptance test for Custom Paint Trimline and shell reuse."""

import math
import os
import sys

import bmesh
import bpy
from mathutils.bvhtree import BVHTree
from mathutils.geometry import interpolate_bezier
from mathutils.kdtree import KDTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators.custom_trim_ops import (  # noqa: E402
    CUSTOM_MASK_NAME,
    _adjust_mask_values,
    _ensure_mask,
    _mask_values,
)
from bl_ext.user_default.rigo_brace.operators.design_ops import (  # noqa: E402
    _inside_polygon,
    _inside_unwrapped_polygon,
    _theta_of,
    _trim_perimeter_uv,
)


def _inside_span(sample, polygon):
    """`_trim_perimeter_uv` returns an UNWRAPPED polygon: a plain planar
    odd-even test against it is wrong for queries past the front seam."""
    angles = [angle for angle, _height in polygon]
    return _inside_unwrapped_polygon(sample, polygon, min(angles), max(angles))


OUT = r"C:\Projects\Blender Add-on Braces\customtrimtest_result.txt"
TRIES = {"count": 0}


def _write(lines):
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))


def _topology(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    boundary = sum(edge.is_boundary for edge in bm.edges)
    nonmanifold = sum(not edge.is_manifold for edge in bm.edges)
    unvisited = set(bm.verts)
    components = 0
    while unvisited:
        components += 1
        pending = [unvisited.pop()]
        while pending:
            vertex = pending.pop()
            neighbours = {
                edge.other_vert(vertex)
                for edge in vertex.link_edges
                if edge.other_vert(vertex) in unvisited
            }
            unvisited.difference_update(neighbours)
            pending.extend(neighbours)
    bm.free()
    return boundary, nonmanifold, components


def _brace_mask_coverage(scan, brace, expected_vertices):
    source_vertices = int(brace.get("rigo_paired_source_vertices", 0))
    scan_tree = KDTree(len(scan.data.vertices))
    mask_values = _mask_values(scan)
    for index, vertex in enumerate(scan.data.vertices):
        scan_tree.insert(scan.matrix_world @ vertex.co, index)
    scan_tree.balance()
    retained_green = 0
    for vertex in list(brace.data.vertices)[:source_vertices]:
        world_coordinate = brace.matrix_world @ vertex.co
        _coordinate, nearest_index, _distance = scan_tree.find(world_coordinate)
        retained_green += int(mask_values[nearest_index] >= 0.5)
    precision = retained_green / max(1, source_vertices)
    coverage = source_vertices / max(1, expected_vertices)
    return source_vertices, precision, coverage


def _paint_reference_region_black(scan, perimeter_data):
    polygon, axis_x, axis_y, front_x, front_y = perimeter_data
    attribute = _ensure_mask(scan)
    selected = 0
    for vertex, color in zip(scan.data.vertices, attribute.data):
        world = scan.matrix_world @ vertex.co
        angle = _theta_of(
            world.x,
            world.y,
            axis_x,
            axis_y,
            front_x,
            front_y,
        ) % math.tau
        inside = _inside_span((angle, world.z), polygon)
        color.color = (0.0, 0.0, 0.0, 1.0) if inside else (1.0, 1.0, 1.0, 1.0)
        selected += int(inside)
    scan.data.update()
    return selected


def _surface_error(scan, perimeter):
    bvh = BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())
    inverse = scan.matrix_world.inverted()
    errors = []
    for point in perimeter.data.splines[0].bezier_points:
        world = perimeter.matrix_world @ point.co
        hit = bvh.find_nearest(inverse @ world)
        if hit[0] is not None:
            surface = scan.matrix_world @ hit[0]
            errors.append(abs((world - surface).length * 1000.0 - 1.5))
    return max(errors, default=999.0)


def _control_turns(perimeter):
    points = [
        perimeter.matrix_world @ point.co
        for point in perimeter.data.splines[0].bezier_points
    ]
    turns = []
    for index, coordinate in enumerate(points):
        incoming = coordinate - points[index - 1]
        outgoing = points[(index + 1) % len(points)] - coordinate
        if incoming.length > 1.0e-9 and outgoing.length > 1.0e-9:
            turns.append(math.degrees(incoming.angle(outgoing)))
    maximum = max(turns)
    return maximum, sum(turns) / len(turns), turns.index(maximum), points[turns.index(maximum)]


def _sampled_turns(perimeter):
    points = perimeter.data.splines[0].bezier_points
    samples = []
    for index, first in enumerate(points):
        second = points[(index + 1) % len(points)]
        samples.extend(
            perimeter.matrix_world @ coordinate
            for coordinate in interpolate_bezier(
                first.co,
                first.handle_right,
                second.handle_left,
                second.co,
                8,
            )[:-1]
        )
    turns = []
    for index, coordinate in enumerate(samples):
        incoming = coordinate - samples[index - 1]
        outgoing = samples[(index + 1) % len(samples)] - coordinate
        if incoming.length > 1.0e-9 and outgoing.length > 1.0e-9:
            turns.append(math.degrees(incoming.angle(outgoing)))
    return max(turns), sum(turns) / len(turns)


def _proper_segment_cross(first, second, third, fourth):
    def side(a, b, point):
        return (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])

    first_side = side(first, second, third)
    second_side = side(first, second, fourth)
    third_side = side(third, fourth, first)
    fourth_side = side(third, fourth, second)
    epsilon = 1.0e-10
    return (
        first_side * second_side < -epsilon
        and third_side * fourth_side < -epsilon
    )


def _polygon_crossings(polygon):
    crossings = 0
    count = len(polygon)
    for first_index in range(count):
        first = polygon[first_index]
        second = polygon[(first_index + 1) % count]
        for third_index in range(first_index + 2, count):
            if (third_index + 1) % count == first_index:
                continue
            third = polygon[third_index]
            fourth = polygon[(third_index + 1) % count]
            crossings += int(_proper_segment_cross(first, second, third, fourth))
    return crossings


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.ops.rigo, "custom_trim_from_paint") and TRIES["count"] < 30:
        return 0.1
    lines = []
    try:
        scan, settings = prepare_reference_design()
        settings.trim_source_mode = "CUSTOM_PAINT"
        template_data = _trim_perimeter_uv(bpy.context)

        paint_result = bpy.ops.rigo.custom_trim_paint()
        paint_settings = bpy.context.tool_settings.vertex_paint
        unified = paint_settings.unified_paint_settings
        brush_green = tuple(round(value, 4) for value in unified.color) == (0.0, 1.0, 0.0)
        brush_white = tuple(round(value, 4) for value in unified.secondary_color) == (1.0, 1.0, 1.0)
        brush_size_ok = unified.size == 50
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        selected = _paint_reference_region_black(scan, template_data)
        black_is_selected = max(_mask_values(scan)) >= 0.99
        alternating_mask = [
            float(index % 3 == 1)
            for index in range(len(scan.data.vertices))
        ]
        grown = _adjust_mask_values(
            scan.data,
            alternating_mask,
            "GROW",
            1,
        )
        kernel_ok = sum(grown) > sum(alternating_mask)

        bpy.ops.rigo.clear_trimlines()
        settings.trim_custom_spacing = 6.0
        custom_result = bpy.ops.rigo.custom_trim_from_paint()
        perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
        spline = perimeter.data.splines[0] if perimeter is not None else None
        controls = len(spline.bezier_points) if spline is not None else 0
        surface_error = _surface_error(scan, perimeter) if perimeter is not None else 999.0
        custom_ok = (
            custom_result == {"FINISHED"}
            and perimeter is not None
            and perimeter.get("rigo_trim_source") == "CUSTOM_PAINT"
            and perimeter.get("rigo_trim_mask_smoothing_passes") == 0
            and spline.use_cyclic_u
            and 24 <= controls <= 240
            and surface_error <= 0.25
        )
        maximum_turn, mean_turn, turn_index, turn_coordinate = _control_turns(perimeter)
        sampled_maximum_turn, sampled_mean_turn = _sampled_turns(perimeter)
        custom_polygon = _trim_perimeter_uv(bpy.context)[0]
        polygon_crossings = _polygon_crossings(custom_polygon)
        mask_values = _mask_values(scan)
        predicted = []
        for vertex in scan.data.vertices:
            world = scan.matrix_world @ vertex.co
            angle = _theta_of(
                world.x,
                world.y,
                float(perimeter["rigo_trim_axis"][0]),
                float(perimeter["rigo_trim_axis"][1]),
                float(perimeter["rigo_trim_front"][0]),
                float(perimeter["rigo_trim_front"][1]),
            ) % math.tau
            predicted.append(_inside_span((angle, world.z), custom_polygon))
        expected = [value >= 0.5 for value in mask_values]
        intersection = sum(wanted and kept for wanted, kept in zip(expected, predicted))
        union = sum(wanted or kept for wanted, kept in zip(expected, predicted))
        mask_iou = intersection / max(1, union)

        settings.corset_thickness = 3.0
        settings.corset_offset = 3.0
        settings.trim_fillet_radius = 0.30
        lines.extend(
            (
                f"paint_result={paint_result}",
                f"brush_green={brush_green} brush_white={brush_white} size_ok={brush_size_ok}",
                f"mask_attribute={CUSTOM_MASK_NAME} black_selected={black_is_selected} painted_vertices={selected}",
                f"mask_kernel_ok={kernel_ok}",
                f"custom_result={custom_result} controls={controls} surface_error_mm={surface_error:.6f}",
                f"control_turn_max_deg={maximum_turn:.6f} mean_deg={mean_turn:.6f}",
                f"control_turn_index={turn_index} coordinate={tuple(round(value, 6) for value in turn_coordinate)}",
                f"sampled_turn_max_deg={sampled_maximum_turn:.6f} mean_deg={sampled_mean_turn:.6f}",
                f"uv_polygon_crossings={polygon_crossings}",
                f"coverage_deg={float(perimeter.get('rigo_trim_angular_coverage_deg', 0.0)):.6f}",
                f"mask_inside_iou={mask_iou:.6f} predicted_vertices={sum(predicted)}",
            )
        )
        if os.environ.get("RIGO_CUSTOM_SKIP_GENERATE") == "1":
            lines.append("PASS=DIAGNOSTIC")
            _write(lines)
            bpy.ops.wm.quit_blender()
            return None
        try:
            generate_result = bpy.ops.rigo.generate_curve_corset()
            generate_error = ""
        except RuntimeError as error:
            generate_result = {"CANCELLED"}
            generate_error = str(error)
        brace = bpy.data.objects.get("Rigo Corset")
        boundary, nonmanifold, components = (
            _topology(brace) if brace is not None else (999, 999, 999)
        )
        source_vertices, mask_precision, mask_coverage = (
            _brace_mask_coverage(scan, brace, selected)
            if brace is not None
            else (0, 0.0, 0.0)
        )
        shell_ok = (
            generate_result == {"FINISHED"}
            and brace is not None
            and boundary == 0
            and nonmanifold == 0
            and components == 1
            and mask_precision >= 0.90
            and mask_coverage >= 0.80
        )
        lines.append(
            f"generate_result={generate_result} boundary={boundary} "
            f"nonmanifold={nonmanifold} components={components} "
            f"error={generate_error!r}"
        )
        lines.append(
            f"source_vertices={source_vertices} "
            f"mask_precision={mask_precision:.6f} "
            f"painted_coverage={mask_coverage:.6f}"
        )
        passed = (
            paint_result == {"FINISHED"}
            and brush_green
            and brush_white
            and brush_size_ok
            and black_is_selected
            and selected > 100
            and kernel_ok
            and custom_ok
            and shell_ok
        )
        lines.append(f"PASS={passed}")
    except Exception as error:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}\nPASS=False")
    _write(lines)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
