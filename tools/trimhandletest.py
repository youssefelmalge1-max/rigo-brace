"""Installed-copy regression for bounded Fusion-style linked tangent edits."""

import bpy
from mathutils import Vector

from bl_ext.user_default.rigo_brace.operators.trimline_ops import (
    _capture_point_states,
    _linked_handle_coordinates,
    _point_states_changed,
    _restore_point_states,
)


OUT = r"C:\Projects\Blender Add-on Braces\trimhandletest_result.txt"


def _run():
    curve = bpy.data.curves.new("Handle Kernel Curve", "CURVE")
    spline = curve.splines.new("BEZIER")
    spline.bezier_points.add(2)
    coordinates = (
        Vector((-0.020, 0.0, 0.0)),
        Vector((0.0, 0.0, 0.0)),
        Vector((0.020, 0.0, 0.0)),
    )
    for point, coordinate in zip(spline.bezier_points, coordinates):
        point.co = coordinate
        point.handle_left_type = "FREE"
        point.handle_right_type = "FREE"
        point.handle_left = coordinate + Vector((-0.004, 0.0, 0.0))
        point.handle_right = coordinate + Vector((0.004, 0.0, 0.0))
    points = spline.bezier_points
    states = _capture_point_states(points)
    target, opposite = _linked_handle_coordinates(
        points[1].co,
        (points[0].co, points[2].co),
        Vector((0.050, 0.030, 0.0)),
        points[1].handle_left,
    )
    points[1].handle_right = target
    points[1].handle_left = opposite
    control_unchanged = (points[1].co - states[1][0]).length <= 1.0e-12
    left_moved = (points[1].handle_left - states[1][1]).length > 1.0e-5
    right_moved = (points[1].handle_right - states[1][2]).length > 1.0e-5
    left = points[1].handle_left - points[1].co
    right = points[1].handle_right - points[1].co
    handles_opposite = left.dot(right) < 0.0
    handles_collinear = left.cross(right).length <= 1.0e-10
    opposite_length_preserved = abs(left.length * 1000.0 - 4.0) <= 1.0e-5
    reach_mm = (points[1].handle_right - points[1].co).length * 1000.0
    reach_bounded = abs(reach_mm - 15.0) <= 1.0e-5
    changed_detected = _point_states_changed(points, states)
    _restore_point_states(points, states)
    restored = not _point_states_changed(points, states)
    passed = (
        control_unchanged
        and left_moved
        and right_moved
        and handles_opposite
        and handles_collinear
        and opposite_length_preserved
        and reach_bounded
        and changed_detected
        and restored
    )
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write(
            f"control_unchanged={control_unchanged}\n"
            f"left_moved={left_moved}\n"
            f"right_moved={right_moved}\n"
            f"handles_opposite={handles_opposite}\n"
            f"handles_collinear={handles_collinear}\n"
            f"opposite_length_preserved={opposite_length_preserved}\n"
            f"reach_mm={reach_mm:.6f}\n"
            f"reach_bounded={reach_bounded}\n"
            f"changed_detected={changed_detected}\n"
            f"restored={restored}\n"
            f"PASS={passed}\n"
        )
    bpy.ops.wm.quit_blender()


if bpy.app.background:
    _run()
