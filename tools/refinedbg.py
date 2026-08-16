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
            fold_pairs, new_start=n_orig, sliver_h=0.12 * target * 0.001,
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
        if bad:
            plan = ro._sliver_dissolve_plan(temp, remaining, n_orig)
            _mark(f"dissolve plan: "
                  f"{None if plan is None else (sorted(plan[0]), plan[1])}")
            if plan is not None:
                temp2 = me.copy()
                added2, target2 = ro._refine_footprint(
                    temp2, group.index, offset
                )
                ro._apply_dissolve(temp2, [plan], n_orig)
                added2 = len(temp2.vertices) - n_orig
                _mark(f"retry refined: +{added2} verts "
                      f"({n_orig} -> {len(temp2.vertices)})")
                weights2 = {}
                for v in temp2.vertices:
                    for g in v.groups:
                        if g.group == group.index:
                            weights2[v.index] = g.weight
                            break
                member2 = {i for i, w in weights2.items() if w > 0.0}
                affected2 = [
                    p for p in temp2.polygons
                    if any(vi in member2 for vi in p.vertices)
                ]
                pre_fn2 = {p.index: p.normal.copy() for p in affected2}
                zone2 = set(member2)
                for p in affected2:
                    zone2.update(p.vertices)
                pre_vn2 = {
                    i: temp2.vertices[i].normal.copy() for i in zone2
                }
                baseline2 = ro._footprint_self_intersections(
                    temp2, member2, affected2
                )
                baseline2 |= {
                    p.index for p in affected2 if p.area < 1e-12
                }
                faired2, adjacency2 = ro._faired_normals(
                    temp2, weights2, mean_edge
                )
                fold_pairs2 = ro._edge_face_pairs(affected2)
                for i in faired2:
                    temp2.vertices[i].co += faired2[i] * (
                        offset * weights2[i]
                    )
                temp2.update()
                remaining2 = ro._repair_folds(
                    temp2, weights2, pre_fn2, pre_vn2, adjacency2,
                    baseline2, affected2, fold_pairs2, new_start=n_orig,
                )
                _mark(f"retry repair remaining={remaining2}")
                for fi in sorted(remaining2)[:12]:
                    p = temp2.polygons[fi]
                    vs = list(p.vertices)
                    ws = [round(weights2.get(i, 0.0), 3) for i in vs]
                    newv = [i >= n_orig for i in vs]
                    els = []
                    for k in range(len(vs)):
                        a, b = vs[k], vs[(k + 1) % len(vs)]
                        els.append(round(
                            (temp2.vertices[a].co
                             - temp2.vertices[b].co).length * 1000.0, 2))
                    _mark(
                        f"  f{fi} w={ws} new={newv} edges_mm={els} "
                        f"area={p.area:.2e} "
                        f"dot_pre={p.normal.dot(pre_fn2[fi]):.3f}"
                    )
                if remaining2:
                    plan2 = ro._sliver_dissolve_plan(
                        temp2, remaining2, n_orig
                    )
                    _mark(f"second dissolve plan: "
                          f"{None if plan2 is None else (sorted(plan2[0]), plan2[1])}")
                bpy.data.meshes.remove(temp2)
        bpy.data.meshes.remove(temp)

        # Ground truth: the OPERATOR path on the same fixture — with the
        # oracle-side forensics: stretched original-original edges classified
        # by PRE-commit crease angle, the dual-confirmation inverted face,
        # and the feather monotonicity reversal edges.
        n_before_op = len(me.vertices)
        before = {v.index: v.co.copy() for v in me.vertices}
        before_n = {v.index: v.normal.copy() for v in me.vertices}
        pre_polys = [tuple(p.vertices) for p in me.polygons]
        # pre-commit dihedral per original edge (footprint zone only).
        pre_edge_deg = {}
        efaces = {}
        for p in me.polygons:
            vs = p.vertices
            for k in range(len(vs)):
                key = tuple(sorted((vs[k], vs[(k + 1) % len(vs)])))
                efaces.setdefault(key, []).append(p.normal.copy())
        member0 = {i for i, w in weights.items() if w > 0.0}
        for key, ns in efaces.items():
            if len(ns) == 2 and (key[0] in member0 or key[1] in member0):
                d0 = max(-1.0, min(1.0, ns[0].dot(ns[1])))
                pre_edge_deg[key] = math.degrees(math.acos(d0))
        # DEFECT-CLASS reference: the same wall committed UNREFINED (the
        # pre-#49 behaviour) — wall-sampling violations with the contract
        # formula, to ground the count separation for the gate.
        tempu = me.copy()
        uw = {}
        for v in me.vertices:
            for g in v.groups:
                if g.group == group.index:
                    uw[v.index] = g.weight
                    break
        member_u = {i for i, w in uw.items() if w > 0.0}
        faired_u, _adj_u = ro._faired_normals(tempu, uw, mean_edge)
        for i in faired_u:
            tempu.vertices[i].co += faired_u[i] * (offset * uw[i])
        tempu.update()
        pre_dih_u = {}
        efaces_u = {}
        for p in me.polygons:
            vs = p.vertices
            for k in range(len(vs)):
                key = tuple(sorted((vs[k], vs[(k + 1) % len(vs)])))
                efaces_u.setdefault(key, []).append(p.normal.copy())
        amount_mm = abs(offset) * 1000.0
        mean_pre_mm = mean_edge * 1000.0
        viol_u = 0
        exceed_u = 0.0
        for key, ns in efaces_u.items():
            a, b = key
            if a not in member_u and b not in member_u:
                continue
            if len(ns) == 2:
                d0 = max(-1.0, min(1.0, ns[0].dot(ns[1])))
                if math.degrees(math.acos(d0)) > 60.0:
                    continue
            pre_len = (me.vertices[a].co - me.vertices[b].co).length
            if pre_len <= 1e-9:
                continue
            g = amount_mm * abs(uw.get(a, 0.0) - uw.get(b, 0.0)) / (
                pre_len * 1000.0
            )
            if g < 0.35:
                continue
            rows = max(4, int(math.ceil(2.0 * math.atan(g) / 0.25)))
            h_req = max(
                1.2, (1.5 * amount_mm / g) * math.sqrt(1.0 + g * g) / rows
            )
            bound = 1.4 * h_req  # absolute (#49b): no mean-edge floor
            post_mm = (
                tempu.vertices[a].co - tempu.vertices[b].co
            ).length * 1000.0
            exceed_u = max(exceed_u, post_mm / bound)
            if post_mm > 1.3 * bound:
                viol_u += 1
        _mark(f"UNREFINED defect reference: wall_viol={viol_u} "
              f"wall_exceed={exceed_u:.2f}")
        bpy.data.meshes.remove(tempu)

        st = bpy.ops.rigo.region_apply()
        region = obj.rigo_regions[obj.rigo_region_index]
        _mark(
            f"operator: st={st} refined_added={region.refined_added} "
            f"target={region.refined_edge_mm:.2f}mm "
            f"verts {n_before_op} -> {len(me.vertices)}"
        )
        from mathutils.bvhtree import BVHTree
        pre_verts = [before[i] for i in range(len(before))]
        surf = BVHTree.FromPolygons(pre_verts, pre_polys, all_triangles=True)
        wpost = {}
        vg = obj.vertex_groups.get(region.surface_mask)
        for v in me.vertices:
            for g in v.groups:
                if g.group == vg.index:
                    wpost[v.index] = g.weight
                    break
        fp = {i for i, w in wpost.items() if w > 1e-5}
        # 1) stretched original-original edges, by pre-crease angle.
        rows = []
        seen_e = set()
        for p in me.polygons:
            vs = p.vertices
            if not any(vi in fp for vi in vs):
                continue
            for k in range(len(vs)):
                a, b = vs[k], vs[(k + 1) % len(vs)]
                key = tuple(sorted((a, b)))
                if key in seen_e or a not in before or b not in before:
                    continue
                seen_e.add(key)
                pre = (before[a] - before[b]).length
                if pre <= 1e-9:
                    continue
                s = (me.vertices[a].co - me.vertices[b].co).length / pre
                if s > 1.5:
                    rows.append((s, pre_edge_deg.get(key)))
        creased = sum(1 for _s, ang in rows if ang is not None and ang > 60.0)
        _mark(
            f"stretched>1.5x: {len(rows)} of which pre-crease>60deg: "
            f"{creased}; angles="
            f"{sorted(round(a, 1) for _s, a in rows if a is not None)}"
        )
        _mark(f"stretch top: "
              f"{sorted((round(s, 2), round(a or -1, 1)) for s, a in rows)[-8:]}")
        # 2) dual-confirmation inverted faces.
        for p in me.polygons:
            vs = p.vertices
            if not any(vi in fp for vi in vs):
                continue
            ref = Vector()
            for vi in vs:
                n = before_n.get(vi)
                if n is not None:
                    ref += n
            center = Vector()
            for vi in vs:
                center += me.vertices[vi].co
            center /= len(vs)
            _loc, nor, _i, _d = surf.find_nearest(center)
            by_verts = ref.length >= 1.5 and p.normal.dot(ref.normalized()) < 0.0
            by_surf = nor is not None and p.normal.dot(nor) < 0.0
            flagged = (by_verts and by_surf) if (
                ref.length >= 1.5 and nor is not None
            ) else (by_verts or (ref.length < 1e-9 and by_surf))
            if flagged:
                newv = [vi >= n_before_op for vi in vs]
                ws = [round(wpost.get(vi, 0.0), 3) for vi in vs]
                els = [round((me.vertices[vs[k]].co
                              - me.vertices[vs[(k + 1) % len(vs)]].co
                              ).length * 1000.0, 2) for k in range(len(vs))]
                _mark(f"oracle-inverted f{p.index} new={newv} w={ws} "
                      f"edges_mm={els} area={p.area:.2e}")
        # 3) feather reversal edges.
        d_all = {}
        for v in me.vertices:
            loc, nor, _i, _d = surf.find_nearest(v.co)
            d_all[v.index] = 0.0 if loc is None else (v.co - loc).dot(nor) * 1000.0
        nrev = 0
        for e in me.edges:
            a, b = e.vertices
            wa, wb = wpost.get(a, 0.0), wpost.get(b, 0.0)
            if wa == wb or (wa == 0.0 and wb == 0.0):
                continue
            if (wa - wb) * (abs(d_all[a]) - abs(d_all[b])) < 0 \
                    and abs(abs(d_all[a]) - abs(d_all[b])) > 0.2:
                nrev += 1
                if nrev <= 10:
                    def _dix(i):
                        if i in before:
                            v = me.vertices[i]
                            return f"{(v.co - before[i]).dot(before_n[i]) * 1000.0:.2f}"
                        return "n/a"
                    _mark(
                        f"rev edge {a}({'new' if a >= n_before_op else 'orig'}"
                        f",w={wa:.3f},d={d_all[a]:.2f},dix={_dix(a)}) - "
                        f"{b}({'new' if b >= n_before_op else 'orig'}"
                        f",w={wb:.3f},d={d_all[b]:.2f},dix={_dix(b)})"
                    )
        _mark(f"rev_total={nrev}")
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
