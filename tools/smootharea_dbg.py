"""#49g: why did 'Smooth Area' give no action for the orthotist?

Three candidate causes, each measured rather than argued:

  A. no selection survives the commit  -> the operator cancels with a status
     warning that is easy to miss (they were in Sculpt Mode; paint lives in
     Edit Mode)
  B. the selection is too SMALL for the new 4-row feather ramp -> every vertex
     sits within the ramp, so strength never reaches full and the visible
     effect collapses
  C. the operator runs correctly but is simply much gentler than the old one
     (HC deliberately undoes the shrinkage that used to be most of the visible
     change), so on an already-clean surface it looks like nothing happened

Evidence only.
"""

import importlib
import os
import sys
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import A_SCAN  # noqa: E402

_OUT = r"C:\Projects\Blender Add-on Braces\smootharea_dbg_result.txt"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _selection_state(obj):
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    faces = sum(1 for f in bm.faces if f.select)
    verts = sum(1 for v in bm.verts if v.select)
    bpy.ops.object.mode_set(mode="OBJECT")
    return faces, verts


def _paint_radius(obj, centre, radius):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    n = 0
    for f in bm.faces:
        if (f.calc_center_median() - centre).length < radius:
            f.select = True
            n += 1
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.object.mode_set(mode="OBJECT")
    return n


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    so = importlib.import_module(
        "bl_ext.user_default.rigo_brace.operators.select_ops"
    )
    settings = bpy.context.scene.rigo_brace
    try:
        bpy.ops.wm.stl_import(filepath=A_SCAN)
        obj = bpy.context.active_object
        settings.scan_object = obj
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        me = obj.data
        cos = [obj.matrix_world @ v.co for v in me.vertices]
        z_min, z_max = min(c.z for c in cos), max(c.z for c in cos)
        y_min, y_max = min(c.y for c in cos), max(c.y for c in cos)
        x_min, x_max = min(c.x for c in cos), max(c.x for c in cos)
        kd = kdtree.KDTree(len(me.vertices))
        for v in me.vertices:
            kd.insert(obj.matrix_world @ v.co, v.index)
        kd.balance()
        _co, seed, _d = kd.find(Vector((
            (x_min + x_max) * 0.5,
            y_min + 0.10 * (y_max - y_min),
            z_min + 0.45 * (z_max - z_min),
        )))
        centre = me.vertices[seed].co.copy()

        # ---- A: does the paint selection survive region_apply? ----
        painted = _paint_radius(obj, centre, 0.059)
        f0, v0 = _selection_state(obj)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 20.0
        settings.region_feather = 15.0
        settings.region_falloff = "SMOOTH"
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.rigo.region_add()
        bpy.ops.object.mode_set(mode="OBJECT")
        f1, v1 = _selection_state(obj)
        bpy.ops.rigo.region_apply()
        f2, v2 = _selection_state(obj)
        _mark(
            f"A selection survival: painted={painted} faces | after paint "
            f"{f0}f/{v0}v | after region_add {f1}f/{v1}v | after commit "
            f"{f2}f/{v2}v"
        )
        _mark(
            "   -> Smooth Area needs a FACE selection; with none it cancels "
            f"with a status-bar warning ({'selection present' if f2 else 'SELECTION EMPTY'})"
        )

        # ---- C: how much does the operator actually move, by patch size? ----
        settings.select_smooth_factor = 0.5
        settings.select_smooth_iters = 5
        for radius_mm in (12.0, 20.0, 35.0, 59.0, 80.0):
            n = _paint_radius(obj, centre, radius_mm * 0.001)
            me = obj.data
            before = [v.co.copy() for v in me.vertices]
            bpy.ops.object.mode_set(mode="EDIT")
            bm = bmesh.from_edit_mesh(me)
            bm.verts.ensure_lookup_table()
            strength = so._feathered_strength(bm, 0.5)
            peak = max(strength.values()) if strength else 0.0
            rows = sum(1 for s in strength.values() if s >= 0.49)
            st = bpy.ops.rigo.smooth_selection()
            bpy.ops.object.mode_set(mode="OBJECT")
            me = obj.data
            moved = max(
                (me.vertices[i].co - before[i]).length
                for i in range(len(before))
            ) * 1000.0
            _mark(
                f"C radius={radius_mm:>5.0f}mm faces={n:>5} "
                f"sel_verts={len(strength):>5} peak_strength={peak:.3f} "
                f"full_strength_verts={rows:>5} -> {st} "
                f"max_move={moved:.3f}mm"
            )
            for i, co in enumerate(before):
                me.vertices[i].co = co
            me.update()

        # ---- B: an already-clean surface has little left to smooth ----
        n = _paint_radius(obj, centre, 0.059)
        me = obj.data
        before = [v.co.copy() for v in me.vertices]
        for run in range(1, 4):
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.rigo.smooth_selection()
            bpy.ops.object.mode_set(mode="OBJECT")
            me = obj.data
            moved = max(
                (me.vertices[i].co - before[i]).length
                for i in range(len(before))
            ) * 1000.0
            _mark(f"B repeated press {run}: cumulative max_move={moved:.3f}mm")
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
