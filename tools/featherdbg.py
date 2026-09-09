"""#54 follow-up probe: how much of a painted area reaches full depth under
the INWARD feather (current semantics), and what an OUTWARD band would cost.

B scan x4, circle r = RIGO_R mm (default 40), PRESSURE amount RIGO_AMOUNT
(default 20), SMOOTH; arms = feathers in RIGO_FEATHERS (default "50,20,5").
Per arm: plateau share, realized depth, outward-band vertex count, then
Commit with rim dihedral p95/max + hinge count.  Writes featherdbg_result.txt.
"""

import heapq
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

_OUT = r"C:\Projects\Blender Add-on Braces\featherdbg_result.txt"
_TRIES = {"n": 0}
_log = []
R_MM = float(os.environ.get("RIGO_R", "40"))
AMOUNT = float(os.environ.get("RIGO_AMOUNT", "20"))
FEATHERS = [float(x) for x in os.environ.get("RIGO_FEATHERS", "50,20,5").split(",")]


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _weights(me, gi):
    out = {}
    for v in me.vertices:
        for g in v.groups:
            if g.group == gi:
                out[v.index] = g.weight
                break
    return out


def _paint_circle(obj, frac_z, r_m):
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
        if (f.calc_center_median() - centre).length < r_m:
            f.select = True
    bmesh.update_edit_mesh(me)


def _outward_band(me, member, feather_m):
    """Vertices OUTSIDE the member set within ``feather_m`` edge-walk of its
    rim (what an outward feather would recruit)."""
    adj = [[] for _ in me.vertices]
    for e in me.edges:
        a, b = e.vertices
        adj[a].append(b)
        adj[b].append(a)
    rim = [i for i in member if any(j not in member for j in adj[i])]
    dist = {i: 0.0 for i in rim}
    heap = [(0.0, i) for i in rim]
    heapq.heapify(heap)
    verts = me.vertices
    while heap:
        d, i = heapq.heappop(heap)
        if d > dist.get(i, 1e30):
            continue
        for j in adj[i]:
            if j in member:
                continue
            nd = d + (verts[i].co - verts[j].co).length
            if nd <= feather_m and nd < dist.get(j, 1e30):
                dist[j] = nd
                heapq.heappush(heap, (nd, j))
    return {i: d for i, d in dist.items() if i not in member}, len(rim)


def _rim_quality(me, member, w=None):
    """Footprint dihedrals; with ``w`` also bins edges past 15 deg by the
    LOWER weight of the edge (rim < 0.05, wall, core >= 0.9)."""
    bm = bmesh.new()
    bm.from_mesh(me)
    angles = []
    bins = {"rim": [0, 0.0], "wall": [0, 0.0], "core": [0, 0.0]}
    for e in bm.edges:
        if len(e.link_faces) != 2:
            continue
        fa, fb = e.link_faces
        if not (any(v.index in member for v in fa.verts)
                and any(v.index in member for v in fb.verts)):
            continue
        d = fa.normal.dot(fb.normal)
        ang = math.degrees(math.acos(max(-1.0, min(1.0, d))))
        angles.append(ang)
        if w is not None and ang > 15.0:
            lo = min(w.get(v.index, 0.0) for v in e.verts)
            key = "rim" if lo < 0.05 else ("core" if lo >= 0.9 else "wall")
            bins[key][0] += 1
            bins[key][1] = max(bins[key][1], ang)
    bm.free()
    a = np.array(angles) if angles else np.zeros(1)
    return (float(np.percentile(a, 95)), float(a.max()),
            int((a > 30).sum()), int((a > 100).sum()), bins)


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
        _mark(f"fixture verts={len(obj.data.vertices)} r={R_MM} amount={AMOUNT} feathers={FEATHERS}")

        for k, feather in enumerate(FEATHERS):
            _paint_circle(obj, 0.45 + 0.12 * k, R_MM * 0.001)
            settings.region_kind = "PRESSURE"
            settings.region_magnitude = AMOUNT
            settings.region_feather = feather
            settings.region_falloff = "SMOOTH"
            bpy.ops.rigo.region_add()
            bpy.ops.object.mode_set(mode="OBJECT")
            region = obj.rigo_regions[obj.rigo_region_index]
            gi = obj.vertex_groups.get(region.surface_mask).index
            w = _weights(obj.data, gi)
            member = set(w)
            wa = np.array(list(w.values()))
            f_eff = min(feather, region.depth_mm)
            band, n_rim = _outward_band(obj.data, member, feather * 0.001)
            _mark(f"[f{feather:g}] members={len(member)} rim={n_rim} max_depth={region.depth_mm:.1f}mm "
                  f"f_eff={f_eff:.1f} share_w>=0.95={float((wa >= 0.95).mean()):.3f} "
                  f"share_w>=0.5={float((wa >= 0.5).mean()):.3f} mean_w={float(wa.mean()):.3f} "
                  f"realized_depth p50={AMOUNT * float(np.median(wa)):.1f}mm "
                  f"| outward band would add {len(band)} verts "
                  f"(+{len(band) / max(1, len(member)):.2f}x), edge_mm={region.edge_mm:.2f}")
            pre = _rim_quality(obj.data, member)
            dg = bpy.context.evaluated_depsgraph_get()
            me_e = obj.evaluated_get(dg).data
            prev = _rim_quality(me_e, member, w)
            n_full = int((wa >= 0.999).sum())
            _mark(f"[f{feather:g}] PREVIEW (what he sees) verts_at_w>=0.999={n_full} "
                  f"dihedral p95/max/over30={prev[0]:.1f}/{prev[1]:.1f}/{prev[2]} "
                  f"edges>15deg by place: {prev[4]}")
            t0 = time.perf_counter()
            result = bpy.ops.rigo.region_apply()
            dt = time.perf_counter() - t0
            post_member = set(_weights(obj.data, gi))
            post = _rim_quality(obj.data, post_member, w)
            _mark(f"[f{feather:g}] commit {result} {dt:.1f}s refined_added={region.refined_added} "
                  f"dihedral p95/max/over30/over100 pre={pre[0]:.1f}/{pre[1]:.1f}/{pre[2]}/{pre[3]} "
                  f"post={post[0]:.1f}/{post[1]:.1f}/{post[2]}/{post[3]} by place {post[4]} note='{region.commit_note}'")
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
