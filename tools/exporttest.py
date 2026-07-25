"""Installed-copy functional test for final-brace STL export."""

import os

import bpy


_OUT = r"C:\Projects\Blender Add-on Braces\exporttest_result.txt"
_STL = r"C:\Projects\Blender Add-on Braces\_exporttest_brace.stl"
_TRIES = {"n": 0}


def _attach_complete_source_record(brace):
    """Give the synthetic export shell real, current source provenance."""
    from bl_ext.user_default.rigo_brace.core.signatures import geometry_signature

    bpy.ops.mesh.primitive_cube_add(location=(0.75, 0.0, 0.0))
    scan = bpy.context.object
    scan.name = "Export Source Scan"

    curve = bpy.data.curves.new("Export Source Perimeter", type="CURVE")
    curve.dimensions = "3D"
    spline = curve.splines.new("POLY")
    spline.points.add(3)
    for point, coordinate in zip(
        spline.points,
        ((-0.10, -0.08, 0.0, 1.0), (0.10, -0.08, 0.0, 1.0),
         (0.10, 0.08, 0.0, 1.0), (-0.10, 0.08, 0.0, 1.0)),
    ):
        point.co = coordinate
    spline.use_cyclic_u = True
    perimeter = bpy.data.objects.new("Rigo Trim Perimeter", curve)
    bpy.context.collection.objects.link(perimeter)

    settings = bpy.context.scene.rigo_brace
    settings.scan_object = scan
    settings.brace_dirty = False
    brace["rigo_source_scan_signature"] = geometry_signature(bpy.context, scan)
    brace["rigo_source_trim_signature"] = geometry_signature(
        bpy.context, perimeter
    )
    brace["rigo_brace_dirty"] = False
    brace["rigo_brace_dirty_reason"] = ""


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1

    lines = []
    try:
        if os.path.exists(_STL):
            os.remove(_STL)

        # A final brace plus a selected, far-away decoy proves export isolates
        # Rigo Corset rather than blindly exporting all selected/active meshes.
        bpy.ops.mesh.primitive_cube_add(location=(0.0, 0.0, 0.0))
        brace = bpy.context.object
        brace.name = "Rigo Corset"
        brace.dimensions = (0.22, 0.16, 0.40)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        expected_dims = tuple(brace.dimensions)
        _attach_complete_source_record(brace)

        bpy.ops.mesh.primitive_cube_add(location=(10.0, 0.0, 0.0))
        decoy = bpy.context.object
        decoy.name = "Export Decoy"
        brace.select_set(True)
        decoy.select_set(True)
        bpy.context.view_layer.objects.active = decoy
        expected_selection = {brace.as_pointer(), decoy.as_pointer()}

        result = bpy.ops.rigo.export_brace(filepath=_STL)
        written = os.path.isfile(_STL) and os.path.getsize(_STL) > 0
        restored_selection = {
            obj.as_pointer() for obj in bpy.context.selected_objects
        }
        selection_restored = (
            bpy.context.view_layer.objects.active == decoy
            and restored_selection == expected_selection
        )
        qa_reran = (
            bool(brace.get("rigo_qa_pass", False))
            and bool(str(brace.get("rigo_qa_signature", "")))
        )

        bpy.ops.wm.stl_import(filepath=_STL)
        imported = bpy.context.object
        imported_dims = tuple(imported.dimensions)
        dimension_error = max(abs(a - b) for a, b in zip(expected_dims, imported_dims))
        isolated = dimension_error < 1.0e-5 and max(imported_dims) < 1.0
        passed = (
            result == {"FINISHED"}
            and written
            and qa_reran
            and selection_restored
            and isolated
        )

        lines.extend(
            (
                f"result={result}",
                f"written={written}",
                f"qa_reran={qa_reran}",
                f"selection_restored={selection_restored}",
                f"expected_dims={expected_dims}",
                f"imported_dims={imported_dims}",
                f"dimension_error={dimension_error:.9f}",
                f"isolated_final_brace={isolated}",
                f"PASS={passed}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={exc!r}\n{traceback.format_exc()}")
        lines.append("PASS=False")
    finally:
        if os.path.exists(_STL):
            os.remove(_STL)

    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
