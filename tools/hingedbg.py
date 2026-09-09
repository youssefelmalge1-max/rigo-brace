"""Ladder trace for the hinge miss (#54 Task 7): the EASEOUT arm of
tools/hingetest.py with the commit ladder's fold check, repair and dissolve
wrapped, then an independent fold census of the shipped mesh.
Writes hingedbg_result.txt.  GUI only.
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

_OUT = r"C:\Projects\Blender Add-on Braces\hingedbg_result.txt"
_TRIES = {"n": 0}
_log = []
PATCH_R = 0.045
FALLOFF = os.environ.get("RIGO_FALLOFF", "EASEOUT")
SCAN = os.environ.get("RIGO_SCAN", "B")  # "sample" = regiontest's coarse fixture
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


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


def _weights(me, gi):
    out = {}
    for v in me.vertices:
        for g in v.groups:
            if g.group == gi:
                out[v.index] = g.weight
                break
    return out


def _census(me, member, tag, new_start=None):
    bm = bmesh.new()
    bm.from_mesh(me)
    worst = 0.0
    bad = []
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
        if ang > 100.0:
            heights = []
            for f in (fa, fb):
                longest = max(l.edge.calc_length() for l in f.loops)
                heights.append(round(2.0 * f.calc_area() / longest * 1000.0, 3))
            bad.append((round(ang, 1), fa.index, fb.index,
                        tuple(v.index for v in e.verts), heights,
                        [v.index >= new_start for v in e.verts] if new_start else None))
    bm.free()
    _mark(f"  census[{tag}] worst={worst:.1f} over100={len(bad)} {bad[:6]}")
    return bad


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


def _wrap(ro):
    STATE = {"n_start": None}
    orig_folded = ro._folded_pairs

    def folded(me, fold_pairs, pre_face_normals):
        out = orig_folded(me, fold_pairs, pre_face_normals)
        worst = 0.0
        exempt = 0
        for a, b in fold_pairs:
            pre = pre_face_normals[a].dot(pre_face_normals[b])
            post = me.polygons[a].normal.dot(me.polygons[b].normal)
            ang = math.degrees(math.acos(max(-1.0, min(1.0, post))))
            if ang > worst:
                worst = ang
            if pre <= ro._FOLD_PRE_DOT and post < ro._FOLD_DOT:
                exempt += 1
        _mark(f"    _folded_pairs pairs={len(fold_pairs)} faces={len(me.polygons)} "
              f"flagged={len(out)} worst_post={worst:.1f} pre_exempt_folds={exempt}")
        if out and STATE.get("dumps", 0) < 2 and STATE.get("w"):
            STATE["dumps"] = STATE.get("dumps", 0) + 1
            w, c = STATE["w"], STATE["c"]
            shown = 0
            for a, b in fold_pairs:
                if a in out and b in out and shown < 6:
                    post = me.polygons[a].normal.dot(me.polygons[b].normal)
                    ang = math.degrees(math.acos(max(-1.0, min(1.0, post))))
                    desc = []
                    for fi in (a, b):
                        desc.append([(vi, round(w.get(vi, 0.0), 3),
                                      "P" if (vi < len(c) and c[vi]) else ("B" if vi in w else "-"))
                                     for vi in me.polygons[fi].vertices])
                    _mark(f"      fold {ang:.1f}deg faces {a},{b}: {desc}")
                    shown += 1
        return out

    ro._folded_pairs = folded
    orig_repair = ro._repair_folds

    def repair(me, *a, **k):
        t0 = time.perf_counter()
        out = orig_repair(me, *a, **k)
        n = len(out) if hasattr(out, "__len__") else out
        _mark(f"  _repair_folds -> remaining={n} faces={len(me.polygons)} "
              f"new_start={k.get('new_start')} {time.perf_counter() - t0:.1f}s")
        STATE["n_start"] = k.get("new_start")
        return out

    ro._repair_folds = repair
    orig_dissolve = ro._apply_dissolve

    def dissolve(temp_me, plans, n_start):
        before = len(temp_me.polygons)
        out = orig_dissolve(temp_me, plans, n_start)
        _mark(f"  _apply_dissolve plans={len(plans)} faces {before}->{len(temp_me.polygons)} -> {out if not hasattr(out, '__len__') else len(out)}")
        return out

    ro._apply_dissolve = dissolve
    return STATE


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
        bpy.ops.wm.stl_import(filepath=_SAMPLE if SCAN == "sample" else B_SCAN)
        obj = bpy.context.active_object
        settings.scan_object = obj
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        if SCAN != "sample":
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.subdivide(number_cuts=1, smoothness=1.0)
            bpy.ops.object.mode_set(mode="OBJECT")
            shade_smooth_scan(obj.data)
        n0 = len(obj.data.vertices)
        _mark(f"fixture verts={n0} falloff={FALLOFF} FOLD_DOT={ro._FOLD_DOT} PRE={ro._FOLD_PRE_DOT}")
        if FALLOFF == "EASEOUT":
            _patch_easeout(ro)
        state = _wrap(ro)
        if SCAN == "sample":
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_mode(type="FACE")
            bpy.ops.mesh.select_all(action="DESELECT")
            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            bm.verts.ensure_lookup_table()
            seed = bm.verts[9000].link_faces[0]
            patch = {seed}
            frontier = [seed]
            while len(patch) < 300 and frontier:
                nxt = []
                for f in frontier:
                    for e in f.edges:
                        for lf in e.link_faces:
                            if lf not in patch:
                                patch.add(lf)
                                nxt.append(lf)
                frontier = nxt
            for f in patch:
                f.select = True
            bmesh.update_edit_mesh(obj.data)
        else:
            _paint_circle(obj, 0.45)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 7.0 if SCAN == "sample" else 15.0
        settings.region_feather = 10.0
        settings.region_falloff = "SMOOTH" if FALLOFF == "EASEOUT" else FALLOFF
        bpy.ops.rigo.region_add()
        bpy.ops.object.mode_set(mode="OBJECT")
        region = obj.rigo_regions[obj.rigo_region_index]
        gi = obj.vertex_groups.get(region.surface_mask).index
        w = _weights(obj.data, gi)
        state["w"] = w
        state["c"] = ro._load_contact(obj.data, region.surface_mask)
        _mark(f"region members={len(w)} outside={region.feather_outside} "
              f"contact={int(ro._load_contact(obj.data, region.surface_mask).sum())}")
        t0 = time.perf_counter()
        result = bpy.ops.rigo.region_apply()
        _mark(f"commit {result} {time.perf_counter() - t0:.1f}s refined_added={region.refined_added} "
              f"note='{region.commit_note}' verts={len(obj.data.vertices)}")
        member = set(_weights(obj.data, gi))
        _census(obj.data, member, "shipped", new_start=n0)
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
