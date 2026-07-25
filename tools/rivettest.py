"""Installed-copy regression for editable circular rivet holes."""

import bpy
import bmesh
from mathutils import Vector


OUT = r"C:\Projects\Blender Add-on Braces\rivettest_result.txt"
TRIES = {"count": 0}


def _write(lines):
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))


def _source_record(brace):
    from bl_ext.user_default.rigo_brace.core.signatures import geometry_signature

    bpy.ops.mesh.primitive_cube_add(location=(2.0, 0.0, 0.0))
    scan = bpy.context.object
    curve = bpy.data.curves.new("Rivet Test Perimeter", type="CURVE")
    spline = curve.splines.new("POLY")
    spline.points.add(2)
    for point, coordinate in zip(spline.points, ((0, 0, 0, 1), (0.1, 0, 0, 1), (0, 0.1, 0, 1))):
        point.co = coordinate
    spline.use_cyclic_u = True
    perimeter = bpy.data.objects.new("Rigo Trim Perimeter", curve)
    bpy.context.collection.objects.link(perimeter)
    settings = bpy.context.scene.rigo_brace
    settings.scan_object = scan
    settings.brace_dirty = False
    settings.design_view_mode = "BRACE"
    brace["rigo_source_scan_signature"] = geometry_signature(bpy.context, scan)
    brace["rigo_source_trim_signature"] = geometry_signature(bpy.context, perimeter)
    brace["rigo_brace_dirty"] = False
    scan.hide_set(True)
    perimeter.hide_set(True)


def _topology(brace):
    bm = bmesh.new()
    bm.from_mesh(brace.data)
    try:
        chi = len(bm.verts) - len(bm.edges) + len(bm.faces)
        boundary = sum(edge.is_boundary for edge in bm.edges)
        nonmanifold = sum(not edge.is_manifold for edge in bm.edges)
        volume = abs(bm.calc_volume(signed=True))
        return chi, boundary, nonmanifold, volume
    finally:
        bm.free()


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.ops.rigo, "cut_rivets") and TRIES["count"] < 30:
        return 0.1
    lines = []
    try:
        from bl_ext.user_default.rigo_brace.operators.rivet_ops import _new_rivet_marker

        bpy.ops.mesh.primitive_cube_add()
        brace = bpy.context.object
        brace.name = "Rigo Corset"
        brace.dimensions = (0.16, 0.004, 0.20)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        _source_record(brace)
        brace.hide_set(False)
        brace.select_set(True)
        bpy.context.view_layer.objects.active = brace
        settings = bpy.context.scene.rigo_brace
        settings.corset_thickness = 4.0
        settings.rivet_diameter = 4.0
        settings.rivet_edge_radius = 0.35
        settings.brace_dirty = False
        brace["rigo_brace_dirty"] = False
        marker = _new_rivet_marker(
            bpy.context, "RIVET_0", Vector((0.0, -0.002, 0.0)), Vector((0.0, -1.0, 0.0)), 4.0
        )
        marker.scale.x = marker.scale.y = 1.0
        before = _topology(brace)
        from bl_ext.user_default.rigo_brace.core import brace_ready_for_finishing
        lines.append(
            f"ready={brace_ready_for_finishing(bpy.context)} dirty={settings.brace_dirty},"
            f"{brace.get('rigo_brace_dirty')} view={settings.design_view_mode} hidden={brace.hide_get()}"
        )
        result = bpy.ops.rigo.cut_rivets()
        after = _topology(brace)
        marker_removed = bpy.data.objects.get("RIVET_0") is None
        passed = (
            result == {"FINISHED"}
            and before[0] - after[0] == 2
            and before[1] == after[1] == 0
            and before[2] == after[2] == 0
            and after[3] < before[3]
            and marker_removed
            and brace.get("rigo_rivet_count") == 1
            and brace.get("rigo_rivet_rounded_edges", 0) >= 2
        )
        lines.extend((f"result={result}", f"topology={before}->{after}", f"marker_removed={marker_removed}", f"status={brace.get('rigo_rivet_status')}", f"PASS={passed}"))
    except Exception as error:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
        lines.append("PASS=False")
    _write(lines)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
