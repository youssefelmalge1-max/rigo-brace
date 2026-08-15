"""#49c evidence: which stage causes the residual wall terracing on coarse
scans — the IDW field (zero gradient at samples), the flat-facet split
placement, or both.  A/B/C/D replica of the commit pipeline on a decim-0.15
steep painted wall, measuring the WALL BAND's dihedral spectrum (terracing =
sharp dihedral rings).  Evidence only."""

import importlib
import math
import traceback

import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

_OUT = r"C:\Projects\Blender Add-on Braces\sculptdbg_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _wall_metrics(me, weights, n_orig, before, pre_polys):
    """Dihedral spectrum of the wall band (0.05<w<0.95) + outside check.

    A PRESSED wall is concave everywhere when smooth; CONVEX wall-band
    edges are the literal speed bumps (terrace ridges) the orthotist sees.
    """
    bm = bmesh.new()
    bm.from_mesh(me)
    angles = []
    ridges = []
    for e in bm.edges:
        a, b = e.verts[0].index, e.verts[1].index
        wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
        if not (0.05 < wa < 0.95 and 0.05 < wb < 0.95):
            continue
        if len(e.link_faces) != 2:
            continue
        try:
            signed = math.degrees(e.calc_face_angle_signed())
        except ValueError:
            signed = 180.0
        angles.append(abs(signed))
        if signed > 10.0:
            ridges.append(signed)
    bm.free()
    angles.sort()
    p95 = angles[int(len(angles) * 0.95)] if angles else 0.0
    amax = angles[-1] if angles else 0.0
    mean = sum(angles) / len(angles) if angles else 0.0
    gt30 = sum(1 for a in angles if a > 30.0)
    ridge_n = len(ridges)
    ridge_max = max(ridges) if ridges else 0.0
    # outside: unweighted verts must sit exactly on the pre-commit surface.
    pre_verts = [before[i] for i in range(len(before))]
    surf = BVHTree.FromPolygons(pre_verts, pre_polys, all_triangles=True)
    outside = 0.0
    for v in me.vertices:
        if v.index in weights:
            continue
        loc, _n, _i, _d = surf.find_nearest(v.co)
        if loc is not None:
            outside = max(outside, (v.co - loc).length * 1000.0)
    return (f"wall_edges={len(angles)} dih_mean={mean:.1f} p95={p95:.1f} "
            f"max={amax:.1f} >30deg={gt30} ridges={ridge_n} "
            f"ridge_max={ridge_max:.1f} outside={outside:.4f}mm")


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    ro = importlib.import_module(
        "bl_ext.user_default.rigo_brace.operators.region_ops"
    )
    try:
        settings = bpy.context.scene.rigo_brace

        # ------------------------------------------------------------------
        # REFERENCE: the same physical patch on the FULL-density scan — the
        # quality ceiling the coarse commit should approach (same zone,
        # 240 faces ≈ 36 coarse faces × 1/0.15).
        # ------------------------------------------------------------------
        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        ref = bpy.context.active_object
        settings.scan_object = ref
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bmr = bmesh.from_edit_mesh(ref.data)
        bmr.verts.ensure_lookup_table()
        frontier = [bmr.verts[9000].link_faces[0]]
        patch = set(frontier)
        while len(patch) < 240 and frontier:
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
        bmesh.update_edit_mesh(ref.data)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 15.0
        settings.region_feather = 10.0
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add()
        ref_region = ref.rigo_regions[ref.rigo_region_index]
        ref_before = {v.index: v.co.copy() for v in ref.data.vertices}
        ref_polys = [tuple(p.vertices) for p in ref.data.polygons]
        ref_norig = len(ref.data.vertices)
        st = bpy.ops.rigo.region_apply()
        wref = {}
        vgr = ref.vertex_groups.get(ref_region.surface_mask)
        for v in ref.data.vertices:
            for g in v.groups:
                if g.group == vgr.index:
                    wref[v.index] = g.weight
                    break
        _mark(f"REFERENCE full-density: st={st} "
              f"refined_added={ref_region.refined_added} "
              + _wall_metrics(ref.data, wref, ref_norig, ref_before,
                              ref_polys))
        bpy.data.objects.remove(ref, do_unlink=True)

        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        obj = bpy.context.active_object
        settings.scan_object = obj
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        anchor = obj.data.vertices[9000].co.copy()
        mod = obj.modifiers.new("DBG_DEC", "DECIMATE")
        mod.ratio = 0.15
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=mod.name)
        me = obj.data
        seed_idx = min(
            range(len(me.vertices)),
            key=lambda i: (me.vertices[i].co - anchor).length_squared,
        )
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(me)
        bm.verts.ensure_lookup_table()
        frontier = [bm.verts[seed_idx].link_faces[0]]
        patch = set(frontier)
        while len(patch) < 36 and frontier:
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
        before = {v.index: v.co.copy() for v in me.vertices}
        pre_polys = [tuple(p.vertices) for p in me.polygons]
        edge_mm = sum(
            (me.vertices[e.vertices[0]].co
             - me.vertices[e.vertices[1]].co).length
            for e in me.edges
        ) / len(me.edges) * 1000.0
        _mark(f"fixture: decim015 verts={n_orig} mean_edge={edge_mm:.1f}mm "
              f"painted 36 faces, 15/10mm")

        def _fair_new(temp, weights, mode, iterations):
            """Post-displacement fairing of NEW weighted verts only —
            originals are fixed anchors carrying their exact clinical
            displacement."""
            zone = {i for i, w in weights.items() if w > 0.0}
            ring = set(zone)
            adj = {}
            for e in temp.edges:
                a, b = e.vertices
                if a in ring or b in ring:
                    adj.setdefault(a, []).append(b)
                    adj.setdefault(b, []).append(a)
            movers = sorted(i for i in zone if i >= n_orig)
            steps = ([(0.5, -0.53)] * iterations if mode == "taubin"
                     else [(0.5, None)] * iterations)
            for lam, mu in steps:
                for factor in (lam, mu):
                    if factor is None:
                        continue
                    deltas = []
                    for i in movers:
                        nbrs = adj.get(i)
                        if not nbrs:
                            continue
                        mean = Vector()
                        for j in nbrs:
                            mean += temp.vertices[j].co
                        mean /= len(nbrs)
                        deltas.append(
                            (i, (mean - temp.vertices[i].co) * factor)
                        )
                    for i, d in deltas:
                        temp.vertices[i].co += d
            temp.update()

        def _phong_resurface(temp, weights, alpha):
            """Re-place every weighted NEW vert on the Phong-curved
            interpolant of the DISPLACED coarse mesh — original verts (the
            exact clinical displacements) are the interpolated anchors."""
            pcoords = [temp.vertices[i].co.copy() for i in range(n_orig)]
            vnormals = [Vector() for _ in range(n_orig)]
            for tri in pre_polys:
                a, b, c = tri
                fn = (pcoords[b] - pcoords[a]).cross(pcoords[c] - pcoords[a])
                for vi in tri:
                    vnormals[vi] += fn
            for n in vnormals:
                if n.length > 1e-12:
                    n.normalize()
            surf = BVHTree.FromPolygons(
                pcoords, pre_polys, all_triangles=True
            )
            from mathutils.geometry import barycentric_transform
            for v in temp.vertices:
                if v.index < n_orig or weights.get(v.index, 0.0) <= 0.0:
                    continue
                loc, _nor, fi, _d = surf.find_nearest(v.co)
                if loc is None:
                    continue
                a, b, c = pre_polys[fi]
                pa, pb, pc = pcoords[a], pcoords[b], pcoords[c]
                # barycentric coords of loc in (pa,pb,pc)
                v0, v1, v2 = pb - pa, pc - pa, loc - pa
                d00, d01, d11 = v0.dot(v0), v0.dot(v1), v1.dot(v1)
                d20, d21 = v2.dot(v0), v2.dot(v1)
                den = d00 * d11 - d01 * d01
                if abs(den) < 1e-20:
                    continue
                wb_ = (d11 * d20 - d01 * d21) / den
                wc_ = (d00 * d21 - d01 * d20) / den
                wa_ = 1.0 - wb_ - wc_
                phong = Vector()
                for bary, pv, nv in ((wa_, pa, vnormals[a]),
                                     (wb_, pb, vnormals[b]),
                                     (wc_, pc, vnormals[c])):
                    proj = loc - nv * (loc - pv).dot(nv)
                    phong += proj * bary
                v.co = loc + (phong - loc) * alpha
            temp.update()

        for tag, curved, harmonic, fair in (
            ("B_curved_idw", True, False, None),
            ("D_curved_harmonic", True, True, None),
        ):
            temp = me.copy()
            added, target = ro._refine_footprint(
                temp, group.index, offset, curved=curved, harmonic=harmonic
            )
            weights = {}
            for v in temp.vertices:
                for g in v.groups:
                    if g.group == group.index:
                        weights[v.index] = g.weight
                        break
            member = {i for i, w in weights.items() if w > 0.0}
            affected = [
                p for p in temp.polygons
                if any(vi in member for vi in p.vertices)
            ]
            pre_fn = {p.index: p.normal.copy() for p in affected}
            zone = set(member)
            for p in affected:
                zone.update(p.vertices)
            pre_vn = {i: temp.vertices[i].normal.copy() for i in zone}
            baseline = ro._footprint_self_intersections(
                temp, member, affected
            )
            baseline |= {p.index for p in affected if p.area < 1e-12}
            faired, adjacency = ro._faired_normals(
                temp, weights, edge_mm * 0.001
            )
            fold_pairs = ro._edge_face_pairs(affected)
            for i in faired:
                temp.vertices[i].co += faired[i] * (offset * weights[i])
            temp.update()
            if fair is not None:
                if fair[0] == "phong":
                    _phong_resurface(temp, weights, fair[1])
                else:
                    _fair_new(temp, weights, fair[0], fair[1])
            remaining = ro._repair_folds(
                temp, weights, pre_fn, pre_vn, adjacency, baseline,
                affected, fold_pairs, new_start=n_orig,
                sliver_h=0.12 * target * 0.001,
            )
            _mark(f"{tag}: +{added} target={target:.2f}mm "
                  f"remaining={len(remaining)} "
                  + _wall_metrics(temp, weights, n_orig, before, pre_polys))
            bpy.data.meshes.remove(temp)

        # Operator ground truth (production defaults).
        st = bpy.ops.rigo.region_apply()
        wpost = {}
        vg = obj.vertex_groups.get(region.surface_mask)
        for v in me.vertices:
            for g in v.groups:
                if g.group == vg.index:
                    wpost[v.index] = g.weight
                    break
        _mark(f"operator: st={st} refined_added={region.refined_added} "
              + _wall_metrics(me, wpost, n_orig, before, pre_polys))
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
