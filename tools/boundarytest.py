"""Functional test for Draw Boundary and exact Bézier library round-trip."""

import importlib
import json

import bpy
from mathutils import Vector


_OUT = r"C:\Projects\Blender Add-on Braces\boundarytest_result.txt"
_SHOT = r"C:\Projects\Blender Add-on Braces\boundary_preview.png"
_TRIES = {"n": 0}
_log = []


def _mark(message):
    _log.append(str(message))
    with open(_OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(_log))


def _library():
    return importlib.import_module("bl_ext.user_default.rigo_brace.core.pad_library")


def _max_nested_delta(first, second):
    return max(
        abs(float(a) - float(b))
        for first_point, second_point in zip(first, second)
        for a, b in zip(first_point, second_point)
    )


def _set_distinct_handles(boundary):
    points = boundary.data.splines[0].bezier_points
    count = len(points)
    for index, point in enumerate(points):
        previous = points[(index - 1) % count].co
        following = points[(index + 1) % count].co
        tangent = (following - previous) * 0.12
        point.handle_left_type = "FREE"
        point.handle_right_type = "FREE"
        point.handle_left = point.co - tangent
        point.handle_right = point.co + tangent


def _frame_selected():
    for area in bpy.context.window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        region = next((region for region in area.regions if region.type == "WINDOW"), None)
        if region is None:
            continue
        with bpy.context.temp_override(area=area, region=region):
            bpy.ops.view3d.view_axis(type="TOP")
            bpy.ops.view3d.view_selected()


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.ops.rigo, "draw_boundary") and _TRIES["n"] < 25:
        return 0.1

    library = _library()
    first_id = None
    second_id = None
    try:
        bpy.ops.mesh.primitive_grid_add(x_subdivisions=31, y_subdivisions=31, size=1.0)
        scan = bpy.context.active_object
        scan.name = "Boundary Test Scan"
        settings = bpy.context.scene.rigo_brace
        settings.scan_object = scan
        settings.pad_kind = "PRESSURE"
        settings.pad_depth = 8.0

        drawn_points = [
            [-0.12, -0.06, 0.0015],
            [0.08, -0.08, 0.0015],
            [0.13, 0.02, 0.0015],
            [0.04, 0.10, 0.0015],
            [-0.10, 0.08, 0.0015],
        ]
        draw_result = bpy.ops.rigo.draw_boundary(points_json=json.dumps(drawn_points))
        boundary = settings.active_pad
        draw_ok = (
            draw_result == {"FINISHED"}
            and boundary is not None
            and boundary.get("rigo_unsaved_boundary") is True
            and len(boundary.data.splines[0].bezier_points) == len(drawn_points)
        )
        _mark(f"phase=draw points={len(drawn_points)} draw_ok={draw_ok}")

        _set_distinct_handles(boundary)
        bpy.context.view_layer.update()
        bpy.ops.rigo.record_pad_shape(name="QA Exact Boundary")
        first_id = settings.pad_type
        first_entry = library.get_entry(first_id)
        saved_ok = (
            first_entry is not None
            and first_entry.get("handle_mode") == "FREE"
            and len(first_entry.get("handles", {}).get("left", ())) == len(drawn_points)
            and len(first_entry.get("handles", {}).get("right", ())) == len(drawn_points)
        )
        library.load_library(force=True)
        persisted_ok = library.get_entry(first_id).get("handles") == first_entry.get("handles")
        _mark(f"phase=save saved_ok={saved_ok} persisted_ok={persisted_ok}")

        first_points = first_entry["points"]
        first_left = first_entry["handles"]["left"]
        first_right = first_entry["handles"]["right"]
        bpy.ops.rigo.clear_pads()
        settings.pad_type = first_id
        bpy.ops.rigo.add_pad(location=(0.0, 0.0, 0.0), use_location=True)
        respawned = settings.active_pad
        free_handles_ok = all(
            point.handle_left_type == "FREE" and point.handle_right_type == "FREE"
            for point in respawned.data.splines[0].bezier_points
        )

        bpy.ops.rigo.record_pad_shape(name="QA Boundary Roundtrip")
        second_id = settings.pad_type
        second_entry = library.get_entry(second_id)
        point_delta = _max_nested_delta(first_points, second_entry["points"])
        left_delta = _max_nested_delta(first_left, second_entry["handles"]["left"])
        right_delta = _max_nested_delta(first_right, second_entry["handles"]["right"])
        roundtrip_ok = free_handles_ok and max(point_delta, left_delta, right_delta) < 1e-4
        _mark(
            f"phase=roundtrip point_delta={point_delta:.2e} left_delta={left_delta:.2e} "
            f"right_delta={right_delta:.2e} roundtrip_ok={roundtrip_ok}"
        )

        edit_result = bpy.ops.rigo.edit_pad()
        edit_ok = edit_result == {"FINISHED"} and bpy.context.mode == "EDIT_CURVE"
        _frame_selected()
        bpy.ops.screen.screenshot(filepath=_SHOT)
        _mark(f"phase=edit mode={bpy.context.mode} edit_ok={edit_ok}")

        passed = draw_ok and saved_ok and persisted_ok and roundtrip_ok and edit_ok
        _mark(f"PASS={passed}")
    except Exception as exc:  # noqa: BLE001
        import traceback

        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")
    finally:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for entry_id in (first_id, second_id):
            if entry_id and library.delete_entry(entry_id):
                library.save_library()

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
