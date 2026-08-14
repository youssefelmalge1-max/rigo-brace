"""#49 diagnosis: classify the faces that stay defective after a refined
commit's repair pass on the paint15 fixture.  Evidence only."""

import importlib
import math
import traceback

import bpy
import bmesh
from mathutils import Vector

_OUT = r"C:\Projects\Blender Add-on Braces\refinedbg_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    ro = importlib.import_module(
        "bl_ext.user_default.rigo_brace.operators.region_ops"
    )
    try:
        settings = bpy.context.scene.rigo_brace
        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        obj = bpy.context.active_object
        settings.scan_object = obj
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        me = obj.data
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(me)
        bm.verts.ensure_lookup_table()
        frontier = [bm.verts[9000].link_faces[0]]
        selected = set(frontier)
        while len(selected) < 240 and frontier:
            nxt = []
            for f in frontier:
                for e in f.edges:
                    for lf in e.link_faces:
                        if lf not in selected:
                            selected.add(lf)
                            nxt.append(lf)
            frontier = nxt
        for f in selected:
            f.select = True
        bmesh.update_edit_mesh(me)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 15.0
        settings.region_feather = 10.0
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add()
        region = obj.rigo_regions[obj.rigo_region_index]
        group = obj.vertex_groups.get(region.surface_mask)
        offset = -region.magnitude_mm * 0.001
        n_orig = len(me.vertices)

        temp = me.copy()
        added, target = ro._refine_footprint(temp, group.index, offset)
        _mark(f"refined: +{added} verts target={target:.2f}mm "
              f"({n_orig} -> {len(temp.vertices)})")

        weights = {}
        for v in temp.vertices:
            for g in v.groups:
                if g.group == group.index:
                    weights[v.index] = g.weight
                    break
        member = {i for i, w in weights.items() if w > 0.0}
        affected = [
            p for p in temp.polygons if any(vi in member for vi in p.vertices)
        ]
        pre_fn = {p.index: p.normal.copy() for p in affected}
        zone = set(member)
        for p in affected:
            zone.update(p.vertices)
        pre_vn = {i: temp.vertices[i].normal.copy() for i in zone}
        edge_total = edge_count = 0
        for e in temp.edges:
            a, b = e.vertices
            if a in member or b in member:
                edge_total += (temp.vertices[a].co - temp.vertices[b].co).length
                edge_count += 1
        mean_edge = edge_total / edge_count
        baseline = ro._footprint_self_intersections(temp, member, affected)
        baseline |= {p.index for p in affected if p.area < 1e-12}
        faired, adjacency = ro._faired_normals(temp, weights, mean_edge)
        fold_pairs = ro._edge_face_pairs(affected)
        for i in faired:
            temp.vertices[i].co += faired[i] * (offset * weights[i])
        temp.update()
        remaining = ro._repair_folds(
            temp, weights, pre_fn, pre_vn, adjacency, baseline, affected,
            fold_pairs,
        )
        _mark(f"repair remaining={remaining}")

        flips = {
            p.index for p in affected
            if p.normal.dot(pre_fn[p.index]) <= 1e-9
        }
        degen = {p.index for p in affected if p.area < 1e-12}
        selfx = ro._footprint_self_intersections(temp, member, affected)
        folds = ro._folded_pairs(temp, fold_pairs, pre_fn)
        bad = (flips | degen | selfx | folds) - baseline
        _mark(
            f"classes: flips={len(flips - baseline)} degen={len(degen - baseline)} "
            f"selfx={len(selfx - baseline)} folds={len(folds - baseline)} "
            f"union={len(bad)}"
        )
        for fi in sorted(bad)[:12]:
            p = temp.polygons[fi]
            vs = list(p.vertices)
            ws = [round(weights.get(i, 0.0), 3) for i in vs]
            newv = [i >= n_orig for i in vs]
            els = []
            for k in range(len(vs)):
                a, b = vs[k], vs[(k + 1) % len(vs)]
                els.append(
                    round((temp.vertices[a].co - temp.vertices[b].co).length
                          * 1000.0, 2)
                )
            kinds = []
            if fi in flips:
                kinds.append("FLIP")
            if fi in degen:
                kinds.append("DEGEN")
            if fi in selfx:
                kinds.append("SELFX")
            if fi in folds:
                kinds.append("FOLD")
            _mark(
                f"  f{fi} {'/'.join(kinds)} w={ws} new={newv} "
                f"edges_mm={els} area={p.area:.2e} "
                f"dot_pre={p.normal.dot(pre_fn[fi]):.3f}"
            )
        bpy.data.meshes.remove(temp)

        # Ground truth: the OPERATOR path on the same fixture.
        n_before_op = len(me.vertices)
        st = bpy.ops.rigo.region_apply()
        region = obj.rigo_regions[obj.rigo_region_index]
        _mark(
            f"operator: st={st} refined_added={region.refined_added} "
            f"target={region.refined_edge_mm:.2f}mm "
            f"verts {n_before_op} -> {len(me.vertices)}"
        )
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
