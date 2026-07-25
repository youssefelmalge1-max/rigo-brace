"""Regression test: re-pressing Paint Area must KEEP the painted region.

1. Fresh import -> Paint Area: the everything-selected import state is wiped.
2. Paint a region, leave Edit Mode, press Paint Area again: region survives.
Writes paintkeeptest_result.txt and self-quits.
"""

import bmesh
import bpy
from mathutils import Vector

_OUT    = r"C:\Projects\Blender Add-on Braces\paintkeeptest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES  = {"n": 0}
_log    = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _count_selected(obj):
    bm = bmesh.from_edit_mesh(obj.data)
    return sum(1 for f in bm.faces if f.select)


def _select_ring(obj, center, radius):
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    n = 0
    for face in bm.faces:
        if (face.calc_center_median() - center).length < radius:
            face.select = True
            n += 1
    for vert in bm.verts:
        vert.select = any(f.select for f in vert.link_faces)
    for edge in bm.edges:
        edge.select = all(v.select for v in edge.verts)
    bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    return n


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        _mark("phase=start")

        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        bpy.context.scene.rigo_brace.scan_object = scan
        bpy.context.view_layer.objects.active = scan

        # ---- 1. fresh import: Paint Area must give a clean slate ---- #
        bpy.ops.rigo.paint_select()
        first = _count_selected(scan)
        clean_ok = first == 0
        _mark(f"phase=first_paint selected={first} clean_ok={clean_ok}")

        # ---- paint a region programmatically ---- #
        bb     = [Vector(c) for c in scan.bound_box]
        size   = (bb[6] - bb[0]).length
        bm_tmp = bmesh.from_edit_mesh(scan.data)
        bm_tmp.faces.ensure_lookup_table()
        target = max(bm_tmp.faces, key=lambda f: f.calc_center_median().x)
        center = target.calc_center_median().copy()
        n_sel  = _select_ring(scan, center, size * 0.10)
        _mark(f"phase=painted faces={n_sel}")

        # ---- 2. leave Edit Mode, press Paint Area again: region kept ---- #
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.rigo.paint_select()
        kept = _count_selected(scan)
        kept_ok = kept == n_sel and kept > 0
        _mark(f"phase=repaint selected={kept} kept_ok={kept_ok}")

        # ---- 3. Clear still wipes it ---- #
        bpy.ops.rigo.select_clear()
        cleared = _count_selected(scan)
        clear_ok = cleared == 0
        _mark(f"phase=cleared selected={cleared} clear_ok={clear_ok}")

        _mark(f"PASS={clean_ok and kept_ok and clear_ok}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
