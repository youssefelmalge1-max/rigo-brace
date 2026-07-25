"""Installed-copy regression for cut and reinforcing manufacturing lattices."""

import bpy
import bmesh


OUT = r"C:\Projects\Blender Add-on Braces\latticepatterntest_result.txt"
TRIES = {"count": 0}


def _write(lines):
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))


def _source_record(brace):
    from bl_ext.user_default.rigo_brace.core.signatures import geometry_signature

    bpy.ops.mesh.primitive_cube_add(location=(2.0, 0.0, 0.0))
    scan = bpy.context.object
    curve = bpy.data.curves.new("Lattice Test Perimeter", type="CURVE")
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


def _new_brace():
    bpy.ops.mesh.primitive_cube_add()
    brace = bpy.context.object
    brace.name = "Rigo Corset"
    brace.dimensions = (0.12, 0.004, 0.14)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    _source_record(brace)
    brace.hide_set(False)
    brace.select_set(True)
    bpy.context.view_layer.objects.active = brace
    return brace


def _select_front(brace):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(brace.data)
    front = min(bm.faces, key=lambda face: face.calc_center_median().y)
    front.select = True
    bm.select_flush(True)
    bmesh.update_edit_mesh(brace.data)


def _metrics(brace):
    bm = bmesh.new()
    bm.from_mesh(brace.data)
    try:
        return (
            abs(bm.calc_volume(signed=True)),
            sum(edge.is_boundary for edge in bm.edges),
            sum(not edge.is_manifold for edge in bm.edges),
        )
    finally:
        bm.free()


def _run_mode(mode, pattern):
    brace = _new_brace()
    settings = bpy.context.scene.rigo_brace
    settings.lattice_finish_mode = mode
    settings.lattice_pattern = pattern
    settings.lattice_cell_size = 18.0
    settings.lattice_bar_width = 4.0
    settings.lattice_height = 1.2
    _select_front(brace)
    before = _metrics(brace)
    result = bpy.ops.rigo.build_lattice_pattern()
    after = _metrics(brace)
    correct_volume = after[0] < before[0] if mode == "CUT" else after[0] > before[0]
    passed = result == {"FINISHED"} and correct_volume and after[1:] == (0, 0) and brace.get("rigo_lattice_cells", 0) > 0
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.data.objects.remove(brace, do_unlink=True)
    return passed, result, before, after


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.ops.rigo, "build_lattice_pattern") and TRIES["count"] < 30:
        return 0.1
    lines = []
    try:
        cut = _run_mode("CUT", "DIAMOND")
        add = _run_mode("ADD", "HEX")
        passed = cut[0] and add[0]
        lines.extend((f"cut={cut}", f"reinforcement={add}", f"PASS={passed}"))
    except Exception as error:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
        lines.append("PASS=False")
    _write(lines)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
