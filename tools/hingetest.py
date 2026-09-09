"""#54 Task 6 — hinge guard: a fold-back between 100 deg and 162 deg never ships.

Reproduces the DEC-0064 EASEOUT arm (falloff t^3 patched into the SMOOTH kind
on the B scan x4 fixture, circle r 45 mm, 15 mm / feather 10), which shipped
a 150.9 deg fold as FINISHED before the guard.  Gates:
1. hinge case: Commit either FINISHES with no adjacent footprint-face pair
   past 100 deg that was smoother than 60 deg before, or is REFUSED with the
   mesh untouched.
2. control: a Rounded 6/6 f15 region on the same mesh still commits FINISHED
   (no false positive on a legitimately steep wall).
Writes hingetest_result.txt (last line PASS=True/False).  GUI only.
"""

import math
import os
import sys
import time
import traceback

import bpy
import bmesh
import numpy as np
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import B_SCAN  # noqa: E402

_OUT = r"C:\Projects\Blender Add-on Braces\hingetest_result.txt"
_TRIES = {"n": 0}
_log = []
_GATES = {}
PATCH_R = 0.045


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _gate(name, ok, detail=""):
    _GATES[name] = bool(ok)
    _mark(f"GATE {name}={'ok' if ok else 'FAIL'} {detail}")


def _patch_easeout(ro):
    orig_f, orig_np, orig_inv = ro._falloff, ro._falloff_np, ro._inv_falloff

    def f(t, kind):
        if kind == "SMOOTH":
            t = min(max(t, 0.0), 1.0)
            return t * t * t
        return orig_f(t, kind)

    def f_np(t, kind):
        if kind == "SMOOTH":
            t = np.clip(t, 0.0, 1.0)
            return t * t * t
        return orig_np(t, kind)

    def inv(y, kind):
        if kind == "SMOOTH":
            return min(1.0, max(0.0, y)) ** (1.0 / 3.0)
        return orig_inv(y, kind)

    ro._falloff, ro._falloff_np, ro._inv_falloff = f, f_np, inv
    return orig_f, orig_np, orig_inv


def _weights(me, gi):
    out = {}
    for v in me.vertices:
        for g in v.groups:
            if g.group == gi:
                out[v.index] = g.weight
                break
    return out


def _hinges(me, member, threshold_deg, pre_normals=None, pre_limit_deg=60.0):
    """Adjacent footprint-face pairs past ``threshold_deg``; with
    ``pre_normals`` only pairs that were smoother than ``pre_limit_deg``."""
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    count = 0
    worst = 0.0
    lim = math.cos(math.radians(threshold_deg))
    pre_lim = math.cos(math.radians(pre_limit_deg))
    for e in bm.edges:
        if len(e.link_faces) != 2:
            continue
        fa, fb = e.link_faces
        if not (any(v.index in member for v in fa.verts)
                and any(v.index in member for v in fb.verts)):
            continue
        d = fa.normal.dot(fb.normal)
        ang = math.degrees(math.acos(max(-1.0, min(1.0, d))))
        worst = max(worst, ang)
        if ang > 60.0:
            areas = [round(f.calc_area() * 1e6, 4) for f in (fa, fb)]
            mins = []
            for f in (fa, fb):
                try:
                    mins.append(round(min(math.degrees(l.calc_angle()) for l in f.loops), 2))
                except ValueError:
                    mins.append(0.0)
            _mark(f"    pair {ang:.1f}deg edge=({e.verts[0].index},{e.verts[1].index}) "
                  f"len={e.calc_length() * 1000:.3f}mm areas_mm2={areas} min_angles={mins} "
                  f"new={[v.index >= 179436 for v in e.verts]}")
        if d < lim:
            if pre_normals is not None:
                pa, pb = pre_normals.get(fa.index), pre_normals.get(fb.index)
                if pa is None or pb is None or pa.dot(pb) <= pre_lim:
                    continue
            count += 1
    bm.free()
    return count, worst


def _paint_circle(obj, frac_z):
    me = obj.data
    mw = obj.matrix_world
    cos = [mw @ v.co for v in me.vertices]
    lo = Vector((min(c.x for c in cos), min(c.y for c in cos), min(c.z for c in cos)))
    hi = Vector((max(c.x for c in cos), max(c.y for c in cos), max(c.z for c in cos)))
    kd = kdtree.KDTree(len(me.vertices))
    for v in me.vertices:
        kd.insert(mw @ v.co, v.index)
    kd.balance()
    _co, seed, _d = kd.find(Vector((
        (lo.x + hi.x) * 0.5, lo.y + 0.10 * (hi.y - lo.y),
        lo.z + frac_z * (hi.z - lo.z),
    )))
    centre = me.vertices[seed].co.copy()
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(me)
    for f in bm.faces:
        if (f.calc_center_median() - centre).length < PATCH_R:
            f.select = True
    bmesh.update_edit_mesh(me)


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        import importlib
        ro = importlib.import_module(
            "bl_ext.user_default.rigo_brace.operators.region_ops"
        )
        from bl_ext.user_default.rigo_brace.operators.scan_ops import (  # noqa
            shade_smooth_scan,
        )
        settings = bpy.context.scene.rigo_brace
        bpy.ops.wm.stl_import(filepath=B_SCAN)
        obj = bpy.context.active_object
        settings.scan_object = obj
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.subdivide(number_cuts=1, smoothness=1.0)
        bpy.ops.object.mode_set(mode="OBJECT")
        shade_smooth_scan(obj.data)
        _mark(f"fixture verts={len(obj.data.vertices)} hinge_deg={ro._HINGE_DEG} pre={ro._HINGE_PRE_DEG}")

        # ---- 1. the EASEOUT hinge case ---- #
        originals = _patch_easeout(ro)
        _paint_circle(obj, 0.45)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 15.0
        settings.region_feather = 10.0
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add()
        bpy.ops.object.mode_set(mode="OBJECT")
        region = obj.rigo_regions[obj.rigo_region_index]
        gi = obj.vertex_groups.get(region.surface_mask).index
        w = _weights(obj.data, gi)
        member = set(w)
        pre_normals = {p.index: p.normal.copy() for p in obj.data.polygons}
        pre_coords = [v.co.copy() for v in obj.data.vertices]
        pre_hinges, pre_worst = _hinges(obj.data, member, ro._HINGE_DEG)
        t0 = time.perf_counter()
        result = bpy.ops.rigo.region_apply()
        dt = time.perf_counter() - t0
        me = obj.data
        finished = result == {"FINISHED"}
        if finished:
            # original faces keep their indices only where unrefined; count
            # every footprint pair past the threshold, ours or not, against
            # the scan's own count (0 on this smooth fixture).
            post_hinges, post_worst = _hinges(me, set(_weights(me, gi)), ro._HINGE_DEG)
            unchanged = False
        else:
            post_hinges, post_worst = pre_hinges, pre_worst
            unchanged = (
                len(me.vertices) == len(pre_coords)
                and all((me.vertices[i].co - pre_coords[i]).length < 1e-12
                        for i in range(len(pre_coords)))
            )
        _mark(f"[easeout] {result} {dt:.1f}s refined_added={region.refined_added} "
              f"pre_hinges={pre_hinges} (worst {pre_worst:.1f}) "
              f"post_hinges={post_hinges} (worst {post_worst:.1f}) unchanged={unchanged}")
        _gate("hinge_never_ships",
              (finished and post_hinges <= pre_hinges) or (not finished and unchanged),
              f"finished={finished} post_hinges={post_hinges} worst={post_worst:.1f} "
              f"(shipped 150.9 before the guard)")

        # ---- 2. control: a real steep wall still commits ---- #
        ro._falloff, ro._falloff_np, ro._inv_falloff = originals
        _paint_circle(obj, 0.65)
        settings.region_falloff = "ROUNDED"
        settings.region_feather = 15.0
        settings.region_top_radius = 6.0
        settings.region_bottom_radius = 6.0
        bpy.ops.rigo.region_add()
        bpy.ops.object.mode_set(mode="OBJECT")
        region2 = obj.rigo_regions[obj.rigo_region_index]
        gi2 = obj.vertex_groups.get(region2.surface_mask).index
        t0 = time.perf_counter()
        result2 = bpy.ops.rigo.region_apply()
        dt2 = time.perf_counter() - t0
        hinges2, worst2 = _hinges(obj.data, set(_weights(obj.data, gi2)), ro._HINGE_DEG)
        _mark(f"[rounded_6_6] {result2} {dt2:.1f}s refined_added={region2.refined_added} "
              f"hinges={hinges2} worst={worst2:.1f}")
        _gate("steep_wall_still_commits",
              result2 == {"FINISHED"} and hinges2 == 0 and region2.refined_added > 0,
              f"{result2} hinges={hinges2} worst={worst2:.1f}")

        failed = [k for k, ok in _GATES.items() if not ok]
        _mark(f"FAILED={failed}")
        _mark(f"PASS={not failed and len(_GATES) >= 2}")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
