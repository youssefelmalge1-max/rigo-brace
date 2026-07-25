"""Installed-copy test for the separate STL and OBJ patient-scan imports."""

import os

import bpy


_OUT = r"C:\Projects\Blender Add-on Braces\importtest_result.txt"
_STL = r"C:\Projects\Blender Add-on Braces\_importtest_scan.stl"
_OBJ = r"C:\Projects\Blender Add-on Braces\_importtest_scan.obj"
_TRIES = {"n": 0}


def _make_fixtures():
    bpy.ops.mesh.primitive_cube_add()
    source = bpy.context.object
    bpy.ops.wm.stl_export(filepath=_STL, export_selected_objects=True)
    bpy.ops.wm.obj_export(filepath=_OBJ, export_selected_objects=True)
    bpy.data.objects.remove(source, do_unlink=True)


def _add_old_patient_trimlines(target):
    for name in ("Rigo Trim Top", "Rigo Trim Bottom", "Rigo Trim Perimeter"):
        curve_data = bpy.data.curves.new(name, "CURVE")
        curve_data.dimensions = "3D"
        spline = curve_data.splines.new("POLY")
        spline.points.add(2)
        trimline = bpy.data.objects.new(name, curve_data)
        bpy.context.scene.collection.objects.link(trimline)
        if name == "Rigo Trim Perimeter":
            modifier = trimline.modifiers.new(
                "Follow Corrected Mold", "SHRINKWRAP"
            )
            modifier.target = target


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1

    lines = []
    try:
        _make_fixtures()
        stl_result = bpy.ops.rigo.import_scan(filepath=_STL, file_format="STL")
        stl_scan = bpy.context.scene.rigo_brace.scan_object
        stl_ok = (
            stl_result == {"FINISHED"}
            and stl_scan == bpy.context.active_object
            and stl_scan.type == "MESH"
            and len(stl_scan.data.vertices) == 8
        )
        _add_old_patient_trimlines(stl_scan)

        obj_result = bpy.ops.rigo.import_scan(filepath=_OBJ, file_format="OBJ")
        obj_scan = bpy.context.scene.rigo_brace.scan_object
        trim_reset_ok = all(
            bpy.data.objects.get(name) is None
            for name in (
                "Rigo Trim Top",
                "Rigo Trim Bottom",
                "Rigo Trim Perimeter",
            )
        )
        obj_ok = (
            obj_result == {"FINISHED"}
            and obj_scan == bpy.context.active_object
            and obj_scan.type == "MESH"
            and len(obj_scan.data.vertices) == 8
            and trim_reset_ok
            and bpy.context.scene.rigo_brace.design_view_mode == "TRIM"
        )

        # A stale perimeter that reappears must still be rejected when its
        # Shrinkwrap belongs to the previous patient scan.
        _add_old_patient_trimlines(stl_scan)
        stale_target_error = ""
        try:
            stale_target_result = bpy.ops.rigo.generate_curve_corset()
        except RuntimeError as exc:
            stale_target_result = {"CANCELLED"}
            stale_target_error = str(exc)
        # Assert the CONTRACT, not one generator's wording: the build is
        # refused, it says so in terms of the trimline and the scan, and it
        # leaves no half-built candidates behind.
        stale_message = stale_target_error.lower()
        stale_target_blocked = (
            stale_target_result == {"CANCELLED"}
            and "trimline" in stale_message
            and "scan" in stale_message
            and bpy.data.objects.get("Rigo Corset Candidate") is None
            and bpy.data.objects.get("Rigo Corset Base Candidate") is None
        )
        try:
            mismatch_rejected = (
                bpy.ops.rigo.import_scan(filepath=_OBJ, file_format="STL")
                == {"CANCELLED"}
            )
        except RuntimeError as exc:
            mismatch_rejected = "Choose a .STL file" in str(exc)
        lines.extend(
            (
                f"stl_result={stl_result} stl_ok={stl_ok}",
                f"obj_result={obj_result} trim_reset_ok={trim_reset_ok} "
                f"obj_ok={obj_ok}",
                f"stale_target_result={stale_target_result} "
                f"error={stale_target_error!r} blocked={stale_target_blocked}",
                f"mismatch_rejected={mismatch_rejected}",
                f"PASS={stl_ok and obj_ok and stale_target_blocked and mismatch_rejected}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={exc!r}\n{traceback.format_exc()}")
        lines.append("PASS=False")
    finally:
        for filepath in (_STL, _OBJ, os.path.splitext(_OBJ)[0] + ".mtl"):
            if os.path.exists(filepath):
                os.remove(filepath)

    with open(_OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
