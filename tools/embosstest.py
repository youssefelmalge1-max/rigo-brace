"""Installed-copy functional test for manufacturing text engraving."""

import bpy
import bmesh
from mathutils import Vector


_OUT = r"C:\Projects\Blender Add-on Braces\embosstest_result.txt"
_TRIES = {"n": 0}


def _attach_complete_source_record(brace):
    """Create the real source provenance required by finishing operators."""
    from bl_ext.user_default.rigo_brace.core.signatures import geometry_signature

    bpy.ops.mesh.primitive_cube_add(location=(0.75, 0.0, 0.0))
    scan = bpy.context.object
    scan.name = "Emboss Source Scan"

    curve = bpy.data.curves.new("Emboss Source Perimeter", type="CURVE")
    curve.dimensions = "3D"
    spline = curve.splines.new("POLY")
    spline.points.add(3)
    for point, coordinate in zip(
        spline.points,
        (
            (-0.10, -0.08, -0.15, 1.0),
            (0.10, -0.08, -0.15, 1.0),
            (0.10, -0.08, 0.15, 1.0),
            (-0.10, -0.08, 0.15, 1.0),
        ),
    ):
        point.co = coordinate
    spline.use_cyclic_u = True
    perimeter = bpy.data.objects.new("Rigo Trim Perimeter", curve)
    bpy.context.collection.objects.link(perimeter)

    settings = bpy.context.scene.rigo_brace
    settings.scan_object = scan
    settings.brace_dirty = False
    settings.design_view_mode = "BRACE"
    brace["rigo_source_scan_signature"] = geometry_signature(bpy.context, scan)
    brace["rigo_source_trim_signature"] = geometry_signature(
        bpy.context, perimeter
    )
    brace["rigo_brace_dirty"] = False
    brace["rigo_brace_dirty_reason"] = ""

    scan.hide_set(True)
    perimeter.hide_set(True)
    brace.hide_set(False)
    scan.select_set(False)
    perimeter.select_set(False)
    brace.select_set(True)
    bpy.context.view_layer.objects.active = brace


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.ops.rigo, "emboss_text") and _TRIES["n"] < 25:
        return 0.1
    lines = []
    try:
        bpy.ops.mesh.primitive_cube_add()
        brace = bpy.context.object
        brace.name = "Rigo Corset"
        brace.dimensions = (0.20, 0.16, 0.30)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        before = (len(brace.data.vertices), len(brace.data.polygons))
        before_bmesh = bmesh.new()
        before_bmesh.from_mesh(brace.data)
        volume_before = abs(before_bmesh.calc_volume(signed=True))
        before_bmesh.free()
        settings = bpy.context.scene.rigo_brace
        # Regression 2026-07-13: finishing polls must be exercised with the
        # same complete, clean source record required in the real workflow.
        _attach_complete_source_record(brace)
        object_ids_before = {obj.as_pointer() for obj in bpy.data.objects}
        poll_ready = bpy.ops.rigo.emboss_text.poll()
        settings.emboss_text = "RIGO"
        settings.emboss_depth = 1.0
        settings.emboss_size = 12.0
        settings.emboss_mode = "RAISED"
        try:
            from bl_ext.user_default.rigo_brace.operators.design_ops import _new_emboss_preview
        except ImportError:
            from rigo_brace.operators.design_ops import _new_emboss_preview
        _new_emboss_preview(
            bpy.context,
            brace,
            settings.emboss_text,
            Vector((0.0, -0.08, 0.0)),
            Vector((0.0, -1.0, 0.0)),
            settings.emboss_size,
        )
        operator_result = bpy.ops.rigo.emboss_text()
        after = (len(brace.data.vertices), len(brace.data.polygons))
        after_bmesh = bmesh.new()
        after_bmesh.from_mesh(brace.data)
        volume_after = abs(after_bmesh.calc_volume(signed=True))
        boundary = sum(edge.is_boundary for edge in after_bmesh.edges)
        nonmanifold = sum(not edge.is_manifold for edge in after_bmesh.edges)
        after_bmesh.free()
        object_ids_after = {obj.as_pointer() for obj in bpy.data.objects}
        temporary_text_removed = object_ids_after == object_ids_before
        passed = (
            poll_ready
            and operator_result == {"FINISHED"}
            and after != before
            and volume_after > volume_before
            and boundary == 0
            and nonmanifold == 0
            and temporary_text_removed
            and brace.get("rigo_emboss_mode") == "RAISED"
        )
        lines.extend(
            (
                f"finishing_poll_ready={poll_ready}",
                f"operator_result={operator_result}",
                f"geometry_before={before}",
                f"geometry_after={after}",
                f"volume={volume_before:.9f}->{volume_after:.9f}",
                f"boundary={boundary} nonmanifold={nonmanifold}",
                f"temporary_text_removed={temporary_text_removed}",
                f"PASS={passed}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={exc!r}\n{traceback.format_exc()}")
        lines.append("PASS=False")
    with open(_OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
