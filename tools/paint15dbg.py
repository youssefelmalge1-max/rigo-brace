"""#49e regression forensics: paint15 (the wrinkled painted fixture) stopped
committing refined after the boundary-distance field landed.

Isolates WHICH half caused it by running the same commit three ways:

  A+B   production as shipped (new bake + rim-field sampling at refinement)
  A     new bake, refinement back on IDW + harmonic interpolation
  none  old Dijkstra bake (weights overwritten by hand), IDW + harmonic

and reports the field's own numbers (rim re-zero, effective feather, wall
slope) plus the per-attempt defect set, so the cause is measured rather than
guessed.  Evidence only.
"""

import heapq
import importlib
import os
import sys
import traceback

import bpy
import bmesh
from mathutils import Vector  # noqa: F401  (used via region_ops)

_SCAN = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_OUT = r"C:\Projects\Blender Add-on Braces\paint15dbg_result.txt"
_TRIES = {"n": 0}
_log = []

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _paint_patch(obj, count=240):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    patch = {bm.verts[9000].link_faces[0]}
    frontier = list(patch)
    while len(patch) < count and frontier:
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


def _import():
    bpy.ops.wm.stl_import(filepath=_SCAN)
    obj = bpy.context.active_object
    settings = bpy.context.scene.rigo_brace
    settings.scan_object = obj
    bpy.context.view_layer.objects.active = obj
    settings.scan_units = "mm"
    bpy.ops.rigo.apply_units()
    return obj, settings


def _old_dijkstra_weights(obj, feather_mm, ro):
    """The pre-#49e bake, recomputed, so the 'none' arm is a true control."""
    me = obj.data
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(me)
    bm.verts.ensure_lookup_table()
    sel = [v for v in bm.verts if v.select]
    sel_set = {v.index for v in sel}
    boundary = [
        v for v in sel
        if any(e.other_vert(v).index not in sel_set for e in v.link_edges)
    ]
    depth = {v.index: 0.0 for v in boundary}
    heap = [(0.0, v.index) for v in boundary]
    heapq.heapify(heap)
    while heap:
        d, idx = heapq.heappop(heap)
        if d > depth.get(idx, 1e30):
            continue
        for e in bm.verts[idx].link_edges:
            o = e.other_vert(bm.verts[idx])
            if o.index not in sel_set:
                continue
            nd = d + e.calc_length()
            if nd < depth.get(o.index, 1e30):
                depth[o.index] = nd
                heapq.heappush(heap, (nd, o.index))
    max_depth = max(depth.values())
    f_eff = min(feather_mm * 0.001, max_depth)
    weights = {
        i: ro._falloff(min(depth.get(i, max_depth), f_eff) / f_eff, "SMOOTH")
        for i in sel_set
    }
    bpy.ops.object.mode_set(mode="OBJECT")
    return weights, max_depth, f_eff


def _field_stats(obj, region, ro, tag):
    me = obj.data
    vg = obj.vertex_groups.get(region.surface_mask)
    weights = {}
    for v in me.vertices:
        for g in v.groups:
            if g.group == vg.index:
                weights[v.index] = g.weight
                break
    member = {i for i, w in weights.items() if w > 0.0}
    zeros = len(weights) - len(member)
    # steepest wall slope: max |dw| per mm over region edges
    slope = 0.0
    for e in me.edges:
        a, b = e.vertices
        if a in weights and b in weights:
            L = (me.vertices[a].co - me.vertices[b].co).length * 1000.0
            if L > 1e-6:
                slope = max(slope, abs(weights[a] - weights[b]) / L)
    _mark(
        f"  [{tag}] field: verts={len(weights)} member={len(member)} "
        f"zero_weight={zeros} max_w={max(weights.values()):.4f} "
        f"steepest={slope:.4f} /mm  (x15mm -> {slope*15:.3f} mm/mm wall)"
    )
    return weights


def _attempt_defects(obj, region, ro, weights, use_field):
    """Replica of commit attempt 0: refine, displace, repair, report."""
    me = obj.data
    vg = obj.vertex_groups.get(region.surface_mask)
    offset = -region.magnitude_mm * 0.001
    n_orig = len(me.vertices)
    rim_field = None
    if use_field:
        rim_field = ro._authored_rim_field(me, vg.index, region.falloff_type)
    temp = me.copy()
    added, tgt = ro._refine_footprint(
        temp, vg.index, offset, field=rim_field
    )
    w = {}
    for v in temp.vertices:
        for g in v.groups:
            if g.group == vg.index:
                w[v.index] = g.weight
                break
    member = {i for i, x in w.items() if x > 0.0}
    affected = [
        p for p in temp.polygons if any(vi in member for vi in p.vertices)
    ]
    pre_fn = {p.index: p.normal.copy() for p in affected}
    zone = set(member)
    for p in affected:
        zone.update(p.vertices)
    pre_vn = {i: temp.vertices[i].normal.copy() for i in zone}
    total = count = 0.0
    for e in temp.edges:
        a, b = e.vertices
        if a in member or b in member:
            total += (temp.vertices[a].co - temp.vertices[b].co).length
            count += 1
    mean_edge = total / count
    baseline = ro._footprint_self_intersections(temp, member, affected)
    baseline |= {p.index for p in affected if p.area < 1e-12}
    faired, adjacency = ro._faired_normals(temp, w, mean_edge)
    fold_pairs = ro._edge_face_pairs(affected)
    for i in faired:
        temp.vertices[i].co += faired[i] * (offset * w[i])
    temp.update()
    remaining = ro._repair_folds(
        temp, w, pre_fn, pre_vn, adjacency, baseline, affected, fold_pairs,
        new_start=n_orig, sliver_h=0.12 * tgt * 0.001,
    )
    all_new = sum(
        1 for fi in remaining
        if all(vi >= n_orig for vi in temp.polygons[fi].vertices)
    )
    touch_new = sum(
        1 for fi in remaining
        if any(vi >= n_orig for vi in temp.polygons[fi].vertices)
    )
    plan = ro._sliver_dissolve_plan(temp, remaining, n_orig)
    selfx_post = ro._footprint_self_intersections(temp, member, affected)
    by_edge = {}
    for p in affected:
        vs = p.vertices
        for k in range(len(vs)):
            a, b = vs[k], vs[(k + 1) % len(vs)]
            key = (b, a) if a > b else (a, b)
            by_edge.setdefault(key, []).append(p.index)
    for fi in sorted(remaining):
        poly = temp.polygons[fi]
        vs = list(poly.vertices)
        worst_post = 1.0
        worst_pre = 1.0
        for k in range(len(vs)):
            a, b = vs[k], vs[(k + 1) % len(vs)]
            key = (b, a) if a > b else (a, b)
            pair = by_edge.get(key, [])
            if len(pair) == 2:
                other = pair[0] if pair[1] == fi else pair[1]
                worst_post = min(
                    worst_post,
                    poly.normal.dot(temp.polygons[other].normal),
                )
                if fi in pre_fn and other in pre_fn:
                    worst_pre = min(
                        worst_pre, pre_fn[fi].dot(pre_fn[other])
                    )
        _mark(
            f"    defect face {fi}: new_verts="
            f"{[vi >= n_orig for vi in vs]} "
            f"w={[round(w.get(vi, 0.0), 3) for vi in vs]} "
            f"area={poly.area:.2e} "
            f"height={2.0*poly.area/max(1e-12, max((temp.vertices[vs[k]].co - temp.vertices[vs[(k+1) % 3]].co).length for k in range(3)))*1000.0:.3f}mm "
            f"selfx={fi in selfx_post} baseline={fi in baseline} "
            f"fold_pre={worst_pre:.2f} fold_post={worst_post:.2f} "
            f"SELF_FLIP={poly.normal.dot(pre_fn[fi]):.3f}"
        )
        for k in range(len(vs)):
            a, b = vs[k], vs[(k + 1) % len(vs)]
            key = (b, a) if a > b else (a, b)
            pair = by_edge.get(key, [])
            if len(pair) == 2:
                other = pair[0] if pair[1] == fi else pair[1]
                if other in pre_fn:
                    _mark(
                        f"      nbr {other}: self_flip="
                        f"{temp.polygons[other].normal.dot(pre_fn[other]):.3f}"
                        f" area={temp.polygons[other].area:.2e}"
                    )
    _mark(
        f"  attempt0: rim_field={rim_field is not None} refined +{added} "
        f"target={tgt:.2f}mm defects={len(remaining)} "
        f"touch_new={touch_new} all_new={all_new} "
        f"plan={'None' if plan is None else str(len(plan[0])) + 'v'}"
    )
    bpy.data.meshes.remove(temp)


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    ro = importlib.import_module(
        "bl_ext.user_default.rigo_brace.operators.region_ops"
    )
    try:
        for tag, use_field, old_bake in (
            ("A+B  shipped", True, False),
            ("A    bake only", False, False),
            ("none control", False, True),
        ):
            obj, settings = _import()
            _paint_patch(obj)
            settings.region_kind = "PRESSURE"
            settings.region_magnitude = 15.0
            settings.region_feather = 10.0
            settings.region_falloff = "SMOOTH"
            old_w = None
            if old_bake:
                old_w, md, fe = _old_dijkstra_weights(obj, 10.0, ro)
                _mark(
                    f"[{tag}] old bake: max_depth={md*1000:.2f}mm "
                    f"f_eff={fe*1000:.2f}mm"
                )
                bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.rigo.region_add()
            region = obj.rigo_regions[obj.rigo_region_index]
            if old_w is not None:
                vg = obj.vertex_groups.get(region.surface_mask)
                for i, x in old_w.items():
                    vg.add([i], x, "REPLACE")
            _mark(f"[{tag}]")
            _field_stats(obj, region, ro, tag)
            _attempt_defects(obj, region, ro, None, use_field)
            st = bpy.ops.rigo.region_apply()
            _mark(
                f"  operator={st} refined_added={region.refined_added} "
                f"edge_mm={region.refined_edge_mm:.2f}"
            )
            bpy.data.objects.remove(obj, do_unlink=True)
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
