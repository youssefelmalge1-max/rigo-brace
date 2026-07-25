"""Quantitative test for three-ring, active-segment Bend/Twist/Stretch."""

import bpy


_OUTPUT = r"C:\Projects\Blender Add-on Braces\segmentdeformtest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"count": 0}
_LOG = []
_RINGS = ("Rigo Lower Ring", "Rigo Middle Ring", "Rigo Upper Ring")


def _mark(message):
    _LOG.append(str(message))
    with open(_OUTPUT, "w", encoding="utf-8") as stream:
        stream.write("\n".join(_LOG))


def _evaluated_coordinates(scan):
    evaluated = scan.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    coordinates = [vertex.co.copy() for vertex in mesh.vertices]
    evaluated.to_mesh_clear()
    return coordinates


def _evaluated_limits(scan):
    evaluated = scan.evaluated_get(bpy.context.evaluated_depsgraph_get())
    modifier = evaluated.modifiers["Rigo Deform"]
    return modifier.limits[:]


def _maximum_motion(before, after, indices):
    return max((after[index] - before[index]).length for index in indices)


def _rigid_distance_error(before, after, indices):
    probes = indices[:: max(1, len(indices) // 12)][:12]
    maximum_error = 0.0
    for first_position, first_index in enumerate(probes):
        for second_index in probes[first_position + 1 :]:
            original = (before[first_index] - before[second_index]).length
            changed = (after[first_index] - after[second_index]).length
            maximum_error = max(maximum_error, abs(changed - original))
    return maximum_error


def _set_ring_fractions(z_min, height, lower, middle, upper):
    bpy.data.objects[_RINGS[0]].location.z = z_min + height * lower
    bpy.data.objects[_RINGS[1]].location.z = z_min + height * middle
    bpy.data.objects[_RINGS[2]].location.z = z_min + height * upper
    bpy.context.view_layer.update()


def _method_amount(settings, method):
    if method == "BEND":
        settings.bend_angle = 20.0
    elif method == "TWIST":
        settings.twist_angle = 20.0
    else:
        settings.stretch_mm = 40.0


def _run():
    _TRIES["count"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["count"] < 25:
        return 0.1
    try:
        _mark("phase=start")
        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        settings = bpy.context.scene.rigo_brace
        settings.scan_object = scan
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        before = [vertex.co.copy() for vertex in scan.data.vertices]
        z_min = min(coordinate.z for coordinate in before)
        z_max = max(coordinate.z for coordinate in before)
        height = z_max - z_min
        lower_indices = [
            index for index, coordinate in enumerate(before)
            if coordinate.z < z_min + height * 0.35
        ]
        upper_indices = [
            index for index, coordinate in enumerate(before)
            if coordinate.z > z_min + height * 0.65
        ]
        bottom_indices = [
            index for index, coordinate in enumerate(before)
            if coordinate.z < z_min + height * 0.03
        ]
        top_indices = [
            index for index, coordinate in enumerate(before)
            if coordinate.z > z_min + height * 0.97
        ]

        method_checks = []
        for method in ("BEND", "TWIST", "STRETCH"):
            settings.deform_segment = "UPPER"
            bpy.ops.rigo.deform_start(method=method)
            rings = [bpy.data.objects.get(name) for name in _RINGS]
            rings_ok = all(
                ring is not None
                and ring.type == "MESH"
                and len(ring.data.polygons) == 1
                and ring.lock_location[0]
                and ring.lock_location[1]
                and not ring.lock_location[2]
                for ring in rings
            )
            _set_ring_fractions(z_min, height, 0.05, 0.55, 0.95)
            upper_status = bpy.ops.rigo.deform_segment(segment="UPPER")
            _method_amount(settings, method)
            upper_coordinates = _evaluated_coordinates(scan)
            upper_limits = _evaluated_limits(scan)
            lower_fixed_mm = _maximum_motion(
                before, upper_coordinates, lower_indices
            ) * 1000.0
            upper_moves_mm = _maximum_motion(
                before, upper_coordinates, upper_indices
            ) * 1000.0
            top_fixed_mm = _maximum_motion(
                before, upper_coordinates, top_indices
            ) * 1000.0
            strict_upper_ok = method == "BEND" or top_fixed_mm < 0.01
            upper_ok = (
                upper_status == {"FINISHED"}
                and abs(upper_limits[0] - 0.55) < 0.01
                and abs(upper_limits[1] - 0.95) < 0.01
                and lower_fixed_mm < 0.01
                and upper_moves_mm > 1.0
                and strict_upper_ok
            )

            lower_status = bpy.ops.rigo.deform_segment(segment="LOWER")
            lower_coordinates = _evaluated_coordinates(scan)
            lower_limits = _evaluated_limits(scan)
            axis = bpy.data.objects.get("Rigo Bend Axis")
            lower_moves_mm = _maximum_motion(
                before, lower_coordinates, lower_indices
            ) * 1000.0
            upper_rigid_error_mm = _rigid_distance_error(
                before, lower_coordinates, upper_indices
            ) * 1000.0
            upper_fixed_mm = _maximum_motion(
                before, lower_coordinates, upper_indices
            ) * 1000.0
            bottom_fixed_mm = _maximum_motion(
                before, lower_coordinates, bottom_indices
            ) * 1000.0
            strict_lower_ok = method == "BEND" or (
                upper_fixed_mm < 0.01 and bottom_fixed_mm < 0.01
            )
            measured_mm_ok = method != "STRETCH" or (
                abs(upper_moves_mm - 40.0) < 0.05
                and abs(lower_moves_mm - 40.0) < 0.05
            )
            lower_ok = (
                lower_status == {"FINISHED"}
                and abs(lower_limits[0] - 0.05) < 0.01
                and abs(lower_limits[1] - 0.55) < 0.01
                and lower_moves_mm > 1.0
                and upper_rigid_error_mm < 0.01
                and strict_lower_ok
                and measured_mm_ok
                and axis is not None
                and axis.parent is rings[0]
            )
            full_status = bpy.ops.rigo.deform_segment(segment="FULL")
            full_limits = _evaluated_limits(scan)
            full_ok = (
                full_status == {"FINISHED"}
                and abs(full_limits[0] - 0.05) < 0.01
                and abs(full_limits[1] - 0.95) < 0.01
                and sum(
                    modifier.name == "Rigo Deform" for modifier in scan.modifiers
                ) == 1
            )
            method_ok = rings_ok and upper_ok and lower_ok and full_ok
            method_checks.append(method_ok)
            _mark(
                f"phase={method.lower()} rings={rings_ok} "
                f"upper_limits=({upper_limits[0]:.3f},{upper_limits[1]:.3f}) "
                f"lower_fixed={lower_fixed_mm:.4f}mm upper_moves={upper_moves_mm:.2f}mm "
                f"top_fixed={top_fixed_mm:.4f}mm "
                f"lower_limits=({lower_limits[0]:.3f},{lower_limits[1]:.3f}) "
                f"lower_moves={lower_moves_mm:.2f}mm upper_fixed={upper_fixed_mm:.4f}mm "
                f"bottom_fixed={bottom_fixed_mm:.4f}mm upper_rigid_err={upper_rigid_error_mm:.4f}mm "
                f"full_limits=({full_limits[0]:.3f},{full_limits[1]:.3f}) "
                f"method_ok={method_ok}"
            )
            bpy.ops.rigo.deform_reset()

        cleanup_ok = all(bpy.data.objects.get(name) is None for name in _RINGS)
        cleanup_ok = cleanup_ok and scan.modifiers.get("Rigo Deform") is None
        cleanup_ok = cleanup_ok and all(
            (vertex.co - before[vertex.index]).length < 1e-12
            for vertex in scan.data.vertices
        )
        _mark(f"phase=cleanup cleanup_ok={cleanup_ok}")
        _mark(f"PASS={all(method_checks) and cleanup_ok}")
    except Exception as exception:  # noqa: BLE001
        import traceback

        _mark(f"ERROR={exception!r}\n{traceback.format_exc()}\nPASS=False")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
