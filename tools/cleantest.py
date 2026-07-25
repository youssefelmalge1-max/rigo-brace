"""Functional test for the Clean stage (Patch 3): center, auto-remesh, verify.

- Center Model: bounding-box centre lands on the world origin.
- Verify Clean-up: detects holes/boundary on the raw open scan; after Fill Holes the
  boundary count drops; after Auto-Remesh the mesh is watertight (boundary 0).
Writes cleantest_result.txt and self-quits. GUI only.
"""

import bpy

_OUT = r"C:\Projects\Blender Add-on Braces\cleantest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _bounds_center(obj):
    import mathutils
    cs = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    return (
        (max(c.x for c in cs) + min(c.x for c in cs)) * 0.5,
        (max(c.y for c in cs) + min(c.y for c in cs)) * 0.5,
        (max(c.z for c in cs) + min(c.z for c in cs)) * 0.5,
    )


def _to_object(context):
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        _mark("phase=start")

        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        settings = bpy.context.scene.rigo_brace
        settings.scan_object = scan
        bpy.context.view_layer.objects.active = scan
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()

        # ---- Center Model ---- #
        bpy.ops.rigo.center_model()
        cx, cy, cz = _bounds_center(scan)
        center_ok = abs(cx) < 1e-3 and abs(cy) < 1e-3 and abs(cz) < 1e-3
        _mark(f"phase=center c=({cx:.4f},{cy:.4f},{cz:.4f}) center_ok={center_ok}")

        # ---- Poke a hole so Verify has something to find (sample is watertight) ---- #
        import bmesh
        _to_object(bpy.context)
        bm = bmesh.new()
        bm.from_mesh(scan.data)
        bm.faces.ensure_lookup_table()
        bm.faces.remove(bm.faces[0])
        bm.to_mesh(scan.data)
        bm.free()
        scan.data.update()

        # ---- Verify detects the hole ---- #
        bpy.ops.rigo.verify_clean()
        _to_object(bpy.context)
        b_hole = scan.get("rigo_boundary", 0)
        detect_ok = b_hole > 0 and scan.get("rigo_verify_ok") is False
        _mark(f"phase=verify_hole boundary={b_hole} detect_ok={detect_ok}")

        # ---- Fill Holes -> boundary drops ---- #
        bpy.ops.rigo.fill_holes()
        bpy.ops.rigo.verify_clean()
        _to_object(bpy.context)
        b_fill = scan.get("rigo_boundary", 0)
        fill_ok = b_fill < b_hole
        _mark(f"phase=verify_fill boundary={b_fill} fill_ok={fill_ok}")

        # ---- Auto-Remesh -> watertight (boundary 0), topology rebuilt ---- #
        faces_before = len(scan.data.polygons)
        bpy.ops.rigo.remesh()
        faces_after = len(scan.data.polygons)
        bpy.ops.rigo.verify_clean()
        _to_object(bpy.context)
        b_remesh = scan.get("rigo_boundary", 0)
        remesh_ok = faces_after != faces_before and b_remesh == 0
        _mark(f"phase=remesh faces={faces_before}->{faces_after} boundary={b_remesh} "
              f"remesh_ok={remesh_ok}")

        _mark(f"PASS={center_ok and detect_ok and fill_ok and remesh_ok}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
