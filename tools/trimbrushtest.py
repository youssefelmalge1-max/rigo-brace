"""Installed-copy viewport regression for the local trimline brush transaction."""

import math
import os
import sys
from types import MethodType, SimpleNamespace

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import interpolate_bezier

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators.trimline_ops import (  # noqa: E402
    RIGO_OT_smooth_trimline_brush,
    _SurfaceRayContext,
    _capture_point_states,
    _cyclic_arc_distances,
    _opening_locked_indices,
    _point_states_changed,
    _point_visible_from_view,
    _raycast_scan_surface,
    _view_ray_origin,
)


MODE = os.environ.get("RIGO_BRUSH_TEST_MODE", "COMMIT").upper()
OUT = (
    r"C:\Projects\Blender Add-on Braces\trimbrushcanceltest_result.txt"
    if MODE == "CANCEL"
    else r"C:\Projects\Blender Add-on Braces\trimbrushtest_result.txt"
)


def _viewport():
    area = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
    region = next(region for region in area.regions if region.type == "WINDOW")
    return area, region, area.spaces.active


def _maximum_turn(curve):
    points = curve.data.splines[0].bezier_points
    samples = []
    for index, first in enumerate(points):
        second = points[(index + 1) % len(points)]
        samples.extend(
            curve.matrix_world @ coordinate
            for coordinate in interpolate_bezier(
                first.co,
                first.handle_right,
                second.handle_left,
                second.co,
                20,
            )[:-1]
        )
    turns = []
    for index, current in enumerate(samples):
        incoming = current - samples[index - 1]
        outgoing = samples[(index + 1) % len(samples)] - current
        if incoming.length > 1.0e-9 and outgoing.length > 1.0e-9:
            turns.append(math.degrees(incoming.angle(outgoing)))
    return max(turns, default=180.0)


def _visible_unlocked_control(region, space, curve, scan):
    bvh = BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())
    points = curve.data.splines[0].bezier_points
    world = [curve.matrix_world @ point.co for point in points]
    locked = _opening_locked_indices(curve, world)
    center = Vector((region.width * 0.5, region.height * 0.5))
    candidates = []
    for index, coordinate in enumerate(world):
        if index in locked:
            continue
        screen = view3d_utils.location_3d_to_region_2d(
            region, space.region_3d, coordinate
        )
        if screen is None:
            continue
        origin = _view_ray_origin(region, space.region_3d, screen, scan)
        if _point_visible_from_view(scan, bvh, origin, coordinate):
            candidates.append(((screen - center).length, index))
    if not candidates:
        raise RuntimeError("No visible unlocked trim control found")
    return min(candidates)[1]


def _surface_backed_event(region, space, curve, scan, index):
    point = curve.data.splines[0].bezier_points[index]
    screen = view3d_utils.location_3d_to_region_2d(
        region, space.region_3d, curve.matrix_world @ point.co
    )
    if screen is None:
        raise RuntimeError("Could not project brush target")
    direction = Vector((region.width * 0.5, region.height * 0.5)) - screen
    if direction.length > 1.0e-9:
        direction.normalize()
    bvh = BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())
    for inset_pixels in range(0, 41, 2):
        candidate = screen + direction * inset_pixels
        event = SimpleNamespace(
            mouse_x=region.x + round(candidate.x),
            mouse_y=region.y + round(candidate.y),
        )
        ray_context = _SurfaceRayContext(region, space.region_3d, scan, bvh)
        if _raycast_scan_surface(ray_context, event) is not None:
            return event
    raise RuntimeError("Could not find a body-backed brush pixel near trimline")


def _surface_bound(scan, coordinates):
    bvh = BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())
    inverse = scan.matrix_world.inverted()
    errors = []
    for coordinate in coordinates:
        hit = bvh.find_nearest(inverse @ coordinate)
        if hit[0] is not None:
            surface = scan.matrix_world @ hit[0]
            errors.append(abs((coordinate - surface).length * 1000.0 - 1.5))
    return max(errors, default=999.0) <= 0.25


def _run_test():
    lines = []
    try:
        scan, settings = prepare_reference_design()
        settings.trim_brush_radius = 90.0
        settings.trim_brush_strength = 0.65
        settings.trim_brush_lock_opening = True
        curve = bpy.data.objects["Rigo Trim Perimeter"]
        area, region, space = _viewport()
        with bpy.context.temp_override(
            window=bpy.context.window,
            screen=bpy.context.screen,
            area=area,
            region=region,
            space_data=space,
        ):
            bpy.context.view_layer.objects.active = scan
            scan.select_set(True)
            bpy.ops.view3d.view_axis(type="FRONT", align_active=False)
            bpy.ops.view3d.view_selected(use_all_regions=False)
            space.region_3d.update()
            index = _visible_unlocked_control(region, space, curve, scan)
            points = curve.data.splines[0].bezier_points
            point_world = curve.matrix_world @ points[index].co
            points[index].co = curve.matrix_world.inverted() @ (
                point_world + Vector((0.0, 0.0, 0.018))
            )
            bpy.ops.rigo.snap_trimline_to_surface()
            for neighbor in (index - 1, index, index + 1):
                point = points[neighbor % len(points)]
                point.handle_left_type = "VECTOR"
                point.handle_right_type = "VECTOR"
            snapshot = _capture_point_states(points)
            before_world = [curve.matrix_world @ state[0] for state in snapshot]
            before_turn = _maximum_turn(curve)
            event = _surface_backed_event(
                region, space, curve, scan, index
            )
            expected_visibility = bool(curve.show_in_front)

            brush_operator = SimpleNamespace(report=lambda *_args: None)
            for method_name in (
                "_prepare",
                "_draw_cursor",
                "_visible_indices",
                "_nearest_control",
                "_dab",
                "_begin_stroke",
                "_commit_stroke",
                "_cleanup",
                "_finish",
            ):
                brush_method = getattr(
                    RIGO_OT_smooth_trimline_brush,
                    method_name,
                )
                setattr(
                    brush_operator,
                    method_name,
                    MethodType(brush_method, brush_operator),
                )
            brush_operator._curve = curve
            brush_operator._scan = scan
            brush_operator._area = area
            brush_operator._region = region
            brush_operator._region_3d = space.region_3d
            brush_operator._prepare(bpy.context)
            brush_operator._begin_stroke(bpy.context, event)
            status_after_dab = str(curve.get("rigo_trim_brush_status", "MISSING"))
            affected = int(curve.get("rigo_trim_brush_affected", 0))
            brush_operator._commit_stroke()
            finish_result = brush_operator._finish(
                bpy.context, cancelled=MODE == "CANCEL"
            )

        points = curve.data.splines[0].bezier_points
        changed = _point_states_changed(points, snapshot)
        visibility_restored = bool(curve.show_in_front) == expected_visibility
        if MODE == "CANCEL":
            passed = (
                status_after_dab == "SMOOTHED"
                and affected > 0
                and not changed
                and finish_result == {"CANCELLED"}
                and visibility_restored
            )
            lines.extend(
                (
                    f"status_after_dab={status_after_dab}",
                    f"affected={affected}",
                    f"cancel_restored={not changed}",
                    f"finish_result={finish_result}",
                    f"visibility_restored={visibility_restored}",
                )
            )
        else:
            after_world = [curve.matrix_world @ point.co for point in points]
            distances = _cyclic_arc_distances(before_world, index)
            outside_unchanged = all(
                (after - before).length <= 1.0e-9
                for before, after, distance in zip(
                    before_world, after_world, distances
                )
                if distance >= 0.090
            )
            after_turn = _maximum_turn(curve)
            smoother = after_turn < before_turn
            surface_bound = _surface_bound(scan, after_world)
            model_linked = (
                curve.get("rigo_trim_handle_model") == "LINKED_TANGENTS"
            )
            passed = (
                status_after_dab == "SMOOTHED"
                and affected > 0
                and changed
                and outside_unchanged
                and smoother
                and surface_bound
                and model_linked
                and finish_result == {"FINISHED"}
                and visibility_restored
            )
            lines.extend(
                (
                    f"status_after_dab={status_after_dab}",
                    f"affected={affected}",
                    f"committed_change={changed}",
                    f"outside_radius_unchanged={outside_unchanged}",
                    f"turn_deg={before_turn:.6f}->{after_turn:.6f}",
                    f"smoother={smoother}",
                    f"surface_bound={surface_bound}",
                    f"handle_model_linked={model_linked}",
                    f"finish_result={finish_result}",
                    f"visibility_restored={visibility_restored}",
                )
            )
    except Exception as error:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
        passed = False
    lines.append(f"PASS={passed}")
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


def _run_when_ready():
    if not hasattr(bpy.ops.rigo, "smooth_trimline_brush"):
        return 0.1
    return _run_test()


bpy.app.timers.register(_run_when_ready, first_interval=0.5)
