"""#49m — does Commit survive a QUAD mesh?

The orthotist works on a quad-remeshed scan.  A crash surfaced by accident
while measuring smoothing:

    ValueError: BVHTree.FromPolygons: non triangle found at index 0
                with length of 4
    _static_faces_bvh (region_ops.py:593) <- RIGO_OT_region_apply

`_static_faces_bvh` passes ``all_triangles=True``, which is a hard assertion
that every polygon is a triangle.  This probe pins down exactly when that is
reached and what the orthotist sees.

GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools/quadcommitdbg.py
"""

import os
import traceback

import bpy
import bmesh

_ROOT = r"C:\Projects\Blender Add-on Braces"
_OUT = os.path.join(_ROOT, "quadcommitdbg_result.txt")
_A_SCAN = os.path.join(_ROOT, "A type model.stl")
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _face_mix(me):
    counts = {}
    for poly in me.polygons:
        counts[len(poly.vertices)] = counts.get(len(poly.vertices), 0) + 1
    return counts


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.5
    try:
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.ops.wm.stl_import(filepath=_A_SCAN)
        obj = bpy.context.active_object
        settings = bpy.context.scene.rigo_brace
        settings.scan_object = obj
        bpy.context.view_layer.objects.active = obj
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        _mark(f"imported STL faces={_face_mix(obj.data)}")

        res = bpy.ops.rigo.remesh()
        obj = bpy.context.scene.rigo_brace.scan_object
        mix = _face_mix(obj.data)
        _mark(f"after rigo.remesh -> {res}  faces={mix}")
        quads = sum(n for k, n in mix.items() if k != 3)
        _mark(f"NON-TRIANGLE faces after our own Remesh: {quads}")

        me = obj.data
        zs = [v.co.z for v in me.vertices]
        zmin, zmax = min(zs), max(zs)
        band = [v for v in me.vertices
                if abs(v.co.z - (zmin + 0.45 * (zmax - zmin))) < 0.01]
        seed = max(band or list(me.vertices), key=lambda v: v.co.x).index

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(me)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        origin = bm.verts[seed].co.copy()
        for face in bm.faces:
            if (face.calc_center_median() - origin).length <= 0.030:
                face.select = True
        bm.select_flush_mode()
        bmesh.update_edit_mesh(me)

        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 20.0
        settings.region_feather = 10.0
        settings.region_falloff = "SMOOTH"
        res = bpy.ops.rigo.region_add()
        _mark(f"region_add -> {res}")
        bpy.ops.object.mode_set(mode="OBJECT")

        _mark("")
        _mark("=== COMMIT on the quad mesh ===")
        try:
            res = bpy.ops.rigo.region_apply()
            _mark(f"region_apply -> {res}   (NO CRASH)")
        except Exception as exc:  # noqa: BLE001
            first = str(exc).strip().splitlines()
            _mark("region_apply RAISED — the orthotist sees a Python error "
                  "popup, not a clean message:")
            for line in first:
                if "Error" in line or "ValueError" in line or "line " in line:
                    _mark(f"    {line.strip()}")
            _mark("")
            _mark("VERDICT: committing a correction on a quad/n-gon scan is a "
                  "hard crash. Our own Mesh-stage Remesh produces quads, so "
                  "Remesh -> Paint -> Commit is broken end to end.")
        _mark("DONE=True")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nDONE=False")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
