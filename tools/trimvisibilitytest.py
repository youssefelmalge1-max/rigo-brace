"""Installed-copy modal regression for hidden trim-point selection."""

import bpy
import math
from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from bl_ext.user_default.rigo_brace.operators.trimline_ops import (
    _point_visible_from_view,
)


OUT = r"C:\Projects\Blender Add-on Braces\trimvisibilitytest_result.txt"
TRIES = {"count": 0}
STATE = {"phase": "WAIT"}
LINES = []


def _write_result(passed):
    LINES.append(f"PASS={passed}")
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(LINES))


def _quit_with_error(error):
    import traceback

    LINES.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    _write_result(False)
    bpy.ops.wm.quit_blender()
    return None


def _viewport():
    area = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
    region = next(region for region in area.regions if region.type == "WINDOW")
    return area, region, area.spaces.active


def _setup_modal_regression():
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=0.12)
    scan = bpy.context.object
    scan.name = "Visibility Test Body"
    settings = bpy.context.scene.rigo_brace
    settings.scan_object = scan

    # First retain the transformed-object kernel regression.  It protects the
    # world/local conversion independently from the modal event path below.
    local_camera = Vector((0.0, -0.50, 0.0))
    local_near = Vector((0.0, -0.1215, 0.0))
    local_far = Vector((0.0, 0.1215, 0.0))
    bvh = BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())
    near_visible = _point_visible_from_view(scan, bvh, local_camera, local_near)
    far_visible = _point_visible_from_view(scan, bvh, local_camera, local_far)

    scan.scale = (0.8, 1.2, 1.1)
    scan.rotation_euler.z = 0.18
    bpy.context.view_layer.update()
    bvh = BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())
    matrix = scan.matrix_world
    transformed_near_visible = _point_visible_from_view(
        scan, bvh, matrix @ local_camera, matrix @ local_near
    )
    transformed_far_visible = _point_visible_from_view(
        scan, bvh, matrix @ local_camera, matrix @ local_far
    )
    kernel_ok = (
        near_visible
        and not far_visible
        and transformed_near_visible
        and not transformed_far_visible
    )
    LINES.extend(
        (
            f"near_visible={near_visible}",
            f"far_visible={far_visible}",
            f"transformed_near_visible={transformed_near_visible}",
            f"transformed_far_visible={transformed_far_visible}",
            f"kernel_ok={kernel_ok}",
        )
    )

    scan.scale = (1.0, 1.0, 1.0)
    scan.rotation_euler.zero()
    bpy.context.view_layer.update()

    area, region, space = _viewport()
    with bpy.context.temp_override(
        window=bpy.context.window,
        screen=bpy.context.screen,
        area=area,
        region=region,
        space_data=space,
    ):
        region_3d = space.region_3d
        region_3d.view_perspective = "ORTHO"
        region_3d.view_rotation.identity()
        region_3d.view_location = (0.0, 0.0, 0.0)
        region_3d.view_distance = 0.60
        region_3d.update()
        area.tag_redraw()
        center = Vector((region.width * 0.5, region.height * 0.5))
        direction = view3d_utils.region_2d_to_vector_3d(
            region, region_3d, center
        ).normalized()
        near_world = -direction * 0.1215
        far_world = direction * 0.1215

        curve_data = bpy.data.curves.new("Visibility Picker Curve", "CURVE")
        curve_data.dimensions = "3D"
        spline = curve_data.splines.new("BEZIER")
        spline.bezier_points.add(1)
        # The hidden point is deliberately first.  The click is placed on its
        # projected pixel, so a proximity-only modal selects the wrong point.
        spline.bezier_points[0].co = far_world
        spline.bezier_points[1].co = near_world
        curve = bpy.data.objects.new("Rigo Trim Perimeter", curve_data)
        bpy.context.scene.collection.objects.link(curve)

        screen_near = view3d_utils.location_3d_to_region_2d(
            region, region_3d, near_world
        )
        screen_far = view3d_utils.location_3d_to_region_2d(
            region, region_3d, far_world
        )
        if screen_near is None or screen_far is None:
            raise RuntimeError("Could not project the modal trim-point fixture")
        click_local = Vector((round(screen_far.x), round(screen_far.y)))
        far_click_distance = (screen_far - click_local).length
        near_click_distance = (screen_near - click_local).length
        click_prefers_hidden = far_click_distance <= near_click_distance
        click_x = region.x + int(click_local.x)
        click_y = region.y + int(click_local.y)
        center_origin = view3d_utils.region_2d_to_origin_3d(
            region, region_3d, center
        )
        right_origin = view3d_utils.region_2d_to_origin_3d(
            region, region_3d, center + Vector((100.0, 0.0))
        )
        screen_right = (right_origin - center_origin).normalized()
        target_normal = (
            -direction * math.cos(math.radians(25.0))
            + screen_right * math.sin(math.radians(25.0))
        ).normalized()
        target_world = target_normal * 0.1215
        target_screen = view3d_utils.location_3d_to_region_2d(
            region, region_3d, target_world
        )
        if target_screen is None:
            raise RuntimeError("Could not project the modal drag target")
        drag_x = region.x + int(round(target_screen.x))
        drag_y = region.y + int(round(target_screen.y))
        snapshot = [point.co.copy() for point in spline.bezier_points]
        view_origin_near = view3d_utils.region_2d_to_origin_3d(
            region, region_3d, screen_near
        )
        direct_near_visible = _point_visible_from_view(
            scan, BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get()),
            view_origin_near, near_world
        )
        view_origin_far = view3d_utils.region_2d_to_origin_3d(
            region, region_3d, screen_far
        )
        direct_far_visible = _point_visible_from_view(
            scan, BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get()),
            view_origin_far, far_world
        )

        expected_show_in_front = bool(curve.show_in_front)
        invoke_result = bpy.ops.rigo.slide_trimline_on_surface("INVOKE_REGION_WIN")

    STATE.update(
        {
            "phase": "PRESS_TARGET",
            "scan": scan,
            "curve": curve,
            "snapshot": snapshot,
            "kernel_ok": kernel_ok,
            "invoke_result": invoke_result,
            "click_x": click_x,
            "click_y": click_y,
            "drag_x": drag_x,
            "drag_y": drag_y,
            "click_prefers_hidden": click_prefers_hidden,
            "projection_delta": (screen_near - screen_far).length,
            "far_click_distance": far_click_distance,
            "near_click_distance": near_click_distance,
            "direct_near_visible": direct_near_visible,
            "direct_far_visible": direct_far_visible,
            "expected_show_in_front": expected_show_in_front,
            "region_geometry": (region.x, region.y, region.width, region.height),
            "window_geometry": (bpy.context.window.width, bpy.context.window.height),
        }
    )
    # Match a real user interaction: move the cursor into the viewport first,
    # then inject the press on the next event-loop turn.
    bpy.context.window.event_simulate(
        type="MOUSEMOVE", value="NOTHING", x=click_x, y=click_y
    )


def _press_target():
    bpy.context.window.event_simulate(
        type="LEFTMOUSE",
        value="PRESS",
        x=STATE["click_x"],
        y=STATE["click_y"],
    )
    STATE["phase"] = "VERIFY_PRESS"


def _verify_press_and_drag():
    points = bpy.data.objects["Rigo Trim Perimeter"].data.splines[0].bezier_points
    hidden_selected = bool(points[0].select_control_point)
    visible_selected = bool(points[1].select_control_point)
    selection_ok = (
        STATE["invoke_result"] == {"RUNNING_MODAL"}
        and STATE["click_prefers_hidden"]
        and STATE["direct_near_visible"]
        and not STATE["direct_far_visible"]
        and visible_selected
        and not hidden_selected
    )
    STATE["selection_ok"] = selection_ok
    LINES.extend(
        (
            f"invoke_result={STATE['invoke_result']}",
            f"projection_delta={STATE['projection_delta']:.6f}",
            f"far_click_distance={STATE['far_click_distance']:.6f}",
            f"near_click_distance={STATE['near_click_distance']:.6f}",
            f"direct_near_visible={STATE['direct_near_visible']}",
            f"direct_far_visible={STATE['direct_far_visible']}",
            f"region_geometry={STATE['region_geometry']}",
            f"window_geometry={STATE['window_geometry']}",
            f"click_window=({STATE['click_x']}, {STATE['click_y']})",
            f"click_prefers_hidden={STATE['click_prefers_hidden']}",
            f"hidden_selected={hidden_selected}",
            f"visible_selected={visible_selected}",
            f"selection_ok={selection_ok}",
        )
    )
    bpy.context.window.event_simulate(
        type="MOUSEMOVE",
        value="NOTHING",
        x=STATE["drag_x"],
        y=STATE["drag_y"],
    )
    STATE["phase"] = "VERIFY_MOVE"


def _verify_move_and_cancel():
    points = STATE["curve"].data.splines[0].bezier_points
    hidden_unchanged = (points[0].co - STATE["snapshot"][0]).length <= 1.0e-9
    visible_moved = (points[1].co - STATE["snapshot"][1]).length > 1.0e-6
    moved_world = STATE["curve"].matrix_world @ points[1].co
    scan = STATE["scan"]
    nearest = BVHTree.FromObject(
        scan, bpy.context.evaluated_depsgraph_get()
    ).find_nearest(scan.matrix_world.inverted() @ moved_world)
    if nearest[0] is None:
        surface_distance_mm = float("inf")
    else:
        surface_world = scan.matrix_world @ nearest[0]
        surface_distance_mm = (moved_world - surface_world).length * 1000.0
    # Trim controls intentionally sit 1.5 mm above the scan.  A point that
    # merely moves, but leaves this surface-following band, is a false pass.
    follows_surface = abs(surface_distance_mm - 1.5) <= 0.25
    movement_ok = (
        STATE["selection_ok"]
        and hidden_unchanged
        and visible_moved
        and follows_surface
    )
    STATE["movement_ok"] = movement_ok
    LINES.extend(
        (
            f"hidden_unchanged_after_drag={hidden_unchanged}",
            f"visible_moved={visible_moved}",
            f"moved_surface_distance_mm={surface_distance_mm:.6f}",
            f"follows_surface={follows_surface}",
            f"drag_pixels={STATE['drag_x'] - STATE['click_x']}",
            f"movement_ok={movement_ok}",
        )
    )
    bpy.context.window.event_simulate(
        type="LEFTMOUSE",
        value="RELEASE",
        x=STATE["drag_x"],
        y=STATE["drag_y"],
    )
    STATE["phase"] = "SEND_CANCEL"


def _send_cancel():
    bpy.context.window.event_simulate(
        type="ESC",
        value="PRESS",
        x=STATE["click_x"],
        y=STATE["click_y"],
    )
    STATE["phase"] = "VERIFY_CANCEL"


def _verify_cancel_and_finish():
    points = STATE["curve"].data.splines[0].bezier_points
    restored = all(
        (point.co - original).length <= 1.0e-9
        for point, original in zip(points, STATE["snapshot"])
    )
    modal_closed = bpy.context.mode == "OBJECT"
    # The editor must restore the prior visibility policy.  The current TRIM
    # view deliberately uses body occlusion, so back points never look as if
    # they pass through the patient.
    show_in_front_restored = (
        bool(STATE["curve"].show_in_front) == STATE["expected_show_in_front"]
    )
    cancel_ok = restored and modal_closed and show_in_front_restored
    passed = (
        STATE["kernel_ok"]
        and STATE["selection_ok"]
        and STATE["movement_ok"]
        and cancel_ok
    )
    LINES.extend(
        (
            f"cancel_restored_snapshot={restored}",
            f"modal_closed={modal_closed}",
            f"show_in_front_restored={show_in_front_restored}",
            f"cancel_ok={cancel_ok}",
        )
    )
    _write_result(passed)
    bpy.ops.wm.quit_blender()
    return None


def _run():
    try:
        phase = STATE["phase"]
        if phase == "WAIT":
            TRIES["count"] += 1
            if (
                (
                    not hasattr(bpy.ops.rigo, "slide_trimline_on_surface")
                    or len(bpy.data.workspaces) != 1
                    or bpy.context.window.workspace.name != "Rigo Brace"
                )
                and TRIES["count"] < 100
            ):
                return 0.1
            _setup_modal_regression()
            return 0.25
        if phase == "VERIFY_PRESS":
            _verify_press_and_drag()
            return 0.25
        if phase == "PRESS_TARGET":
            _press_target()
            return 0.25
        if phase == "VERIFY_MOVE":
            _verify_move_and_cancel()
            return 0.25
        if phase == "SEND_CANCEL":
            _send_cancel()
            return 0.25
        if phase == "VERIFY_CANCEL":
            return _verify_cancel_and_finish()
        raise RuntimeError(f"Unknown trim visibility test phase: {phase}")
    except Exception as error:  # noqa: BLE001
        return _quit_with_error(error)


bpy.app.timers.register(_run, first_interval=0.5)
