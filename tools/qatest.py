"""Installed-copy functional test for the final manufacturing QA gate."""

import bpy
import bmesh


_OUT = r"C:\Projects\Blender Add-on Braces\qatest_result.txt"
_TRIES = {"n": 0}


def _clear():
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def _cube(name="Rigo Corset", dimensions=(0.22, 0.16, 0.40)):
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj


def _attach_complete_source_record(brace):
    """Give a synthetic QA shell real, current scan/perimeter provenance."""
    from bl_ext.user_default.rigo_brace.core.signatures import geometry_signature

    bpy.ops.mesh.primitive_cube_add(location=(0.75, 0.0, 0.0))
    scan = bpy.context.object
    scan.name = "QA Source Scan"

    curve = bpy.data.curves.new("QA Source Perimeter", type="CURVE")
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


def _call_qa():
    try:
        return bpy.ops.rigo.verify_brace_qa()
    except RuntimeError:
        # bpy raises for an operator ERROR report even though the operator also
        # records the failed QA state on the brace.
        return {"CANCELLED"}


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.ops.rigo, "verify_brace_qa") and _TRIES["n"] < 25:
        return 0.1

    lines = []
    try:
        scene = bpy.context.scene
        scene.unit_settings.system = "METRIC"
        scene.unit_settings.length_unit = "MILLIMETERS"
        scene.unit_settings.scale_length = 1.0
        scene.rigo_brace.qa_min_thickness = 3.0

        _clear()
        good = _cube()
        _attach_complete_source_record(good)
        good_result = _call_qa()
        good_pass = good_result == {"FINISHED"} and bool(good.get("rigo_qa_pass"))
        good_min = float(good.get("rigo_qa_min_thickness_mm", 0.0))

        _clear()
        open_mesh = _cube()
        bm = bmesh.new()
        bm.from_mesh(open_mesh.data)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[bm.faces[0]], context="FACES")
        bm.to_mesh(open_mesh.data)
        bm.free()
        _attach_complete_source_record(open_mesh)
        open_result = _call_qa()
        open_blocked = (
            open_result == {"CANCELLED"}
            and not bool(open_mesh.get("rigo_qa_pass"))
            and int(open_mesh.get("rigo_qa_boundary", 0)) > 0
        )

        _clear()
        thin = _cube(dimensions=(0.002, 0.16, 0.40))
        _attach_complete_source_record(thin)
        thin_result = _call_qa()
        thin_min = float(thin.get("rigo_qa_min_thickness_mm", 0.0))
        thin_coverage = float(thin.get("rigo_qa_thickness_coverage", 0.0))
        thin_report = str(thin.get("rigo_qa_report", ""))
        thin_metric_recorded = (
            "rigo_qa_min_thickness_mm" in thin
            and 0.0 < thin_min < 3.0
            and thin_coverage >= 0.80
        )
        thin_blocked = (
            thin_result == {"CANCELLED"}
            and thin_metric_recorded
            and "Minimum sampled wall" in thin_report
        )

        passed = good_pass and good_min >= 3.0 and open_blocked and thin_blocked
        lines.extend(
            (
                f"good_result={good_result}",
                f"good_pass={good_pass}",
                f"good_min_mm={good_min:.4f}",
                f"open_result={open_result}",
                f"open_blocked={open_blocked}",
                f"thin_result={thin_result}",
                f"thin_min_mm={thin_min:.4f}",
                f"thin_coverage={thin_coverage:.4f}",
                f"thin_metric_recorded={thin_metric_recorded}",
                f"thin_report={thin_report}",
                f"thin_blocked={thin_blocked}",
                f"PASS={passed}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={exc!r}\n{traceback.format_exc()}")
        lines.append("PASS=False")

    with open(_OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
