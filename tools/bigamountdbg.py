"""#49d evidence: why the refined wall falls back at BIG amounts on the
A-model waist patch (5 mm survives, 20 mm falls back -> staircase -> sculpt
smoothing tears a spike crown).  Per-amount replica of attempt 0 with defect
classes, clustering, and the dissolve-plan verdict.  Evidence only."""

import importlib
import os
import sys
import time
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import A_SCAN  # noqa: E402

_OUT = r"C:\Projects\Blender Add-on Braces\bigamountdbg_result.txt"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _clusters(me, remaining):
    """Connected components of the defective faces (shared verts)."""
    remaining = set(remaining)
    comps = []
    pool = set(remaining)
    fverts = {fi: set(me.polygons[fi].vertices) for fi in remaining}
    while pool:
        seed = pool.pop()
        comp = {seed}
        frontier = [seed]
        while frontier:
            f = frontier.pop()
            for g in list(pool):
                if fverts[f] & fverts[g]:
                    pool.discard(g)
                    comp.add(g)
                    frontier.append(g)
        comps.append(comp)
    return comps


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    ro = importlib.import_module(
        "bl_ext.user_default.rigo_brace.operators.region_ops"
    )
    settings = bpy.context.scene.rigo_brace
    try:
        for amount, feather in (
            (20.0, 15.0),
        ):
            bpy.ops.wm.stl_import(filepath=A_SCAN)
            obj = bpy.context.active_object
            settings.scan_object = obj
            settings.scan_units = "mm"
            bpy.ops.rigo.apply_units()
            me = obj.data
            cos = [obj.matrix_world @ v.co for v in me.vertices]
            z_min = min(c.z for c in cos)
            z_max = max(c.z for c in cos)
            y_min, y_max = min(c.y for c in cos), max(c.y for c in cos)
            x_min, x_max = min(c.x for c in cos), max(c.x for c in cos)
            cx = (x_min + x_max) * 0.5
            dz, dy = z_max - z_min, y_max - y_min
            target = Vector((cx, y_min + 0.10 * dy, z_min + 0.45 * dz))
            kd = kdtree.KDTree(len(me.vertices))
            for v in me.vertices:
                kd.insert(obj.matrix_world @ v.co, v.index)
            kd.balance()
            _co, seed, _d = kd.find(target)
            center = me.vertices[seed].co.copy()
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_mode(type="FACE")
            bpy.ops.mesh.select_all(action="DESELECT")
            bm = bmesh.from_edit_mesh(me)
            for f in bm.faces:
                if (f.calc_center_median() - center).length < 0.059:
                    f.select = True
            bmesh.update_edit_mesh(me)
            settings.region_kind = "PRESSURE"
            settings.region_magnitude = amount
            settings.region_feather = feather
            settings.region_falloff = "SMOOTH"
            bpy.ops.rigo.region_add()
            region = obj.rigo_regions[obj.rigo_region_index]
            group = obj.vertex_groups.get(region.surface_mask)
            offset = -region.magnitude_mm * 0.001
            n_orig = len(me.vertices)

            temp = me.copy()
            added, tgt = ro._refine_footprint(temp, group.index, offset)
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
            edge_total = edge_count = 0
            for e in temp.edges:
                a, b = e.vertices
                if a in member or b in member:
                    edge_total += (
                        temp.vertices[a].co - temp.vertices[b].co
                    ).length
                    edge_count += 1
            mean_edge = edge_total / edge_count
            baseline = ro._footprint_self_intersections(
                temp, member, affected
            )
            baseline |= {p.index for p in affected if p.area < 1e-12}
            faired, adjacency = ro._faired_normals(temp, weights, mean_edge)
            fold_pairs = ro._edge_face_pairs(affected)
            for i in faired:
                temp.vertices[i].co += faired[i] * (offset * weights[i])
            temp.update()
            remaining = ro._repair_folds(
                temp, weights, pre_fn, pre_vn, adjacency, baseline,
                affected, fold_pairs, new_start=n_orig,
                sliver_h=0.12 * tgt * 0.001,
            )
            comps = _clusters(temp, remaining)
            all_new_faces = sum(
                1 for fi in remaining
                if all(vi >= n_orig for vi in temp.polygons[fi].vertices)
            )
            touch_new = sum(
                1 for fi in remaining
                if any(vi >= n_orig for vi in temp.polygons[fi].vertices)
            )
            plan = ro._sliver_dissolve_plan(temp, remaining, n_orig)
            _mark(
                f"amount={amount:.0f}/{feather:.0f}mm: refined +{added} "
                f"tgt={tgt:.2f}mm "
                f"remaining={len(remaining)} clusters={len(comps)} "
                f"sizes={sorted(len(c) for c in comps)} "
                f"touch_new={touch_new} all_new={all_new_faces} "
                f"plan={'None' if plan is None else f'{len(plan[0])}v'}"
            )
            bpy.data.meshes.remove(temp)

            if plan is not None:
                # What does the dissolve weld leave?  Non-manifold delta +
                # classification of the offending edges.
                temp2 = me.copy()
                nm0 = ro._nonmanifold_count(me)
                ro._refine_footprint(temp2, group.index, offset)
                ro._apply_dissolve(temp2, [plan], n_orig)
                nm1 = ro._nonmanifold_count(temp2)
                _mark(f"  dissolve-weld nonman: {nm0} -> {nm1}")
                if nm1 != nm0:
                    counts = {}
                    for p in temp2.polygons:
                        vs = p.vertices
                        for k in range(len(vs)):
                            a2, b2 = vs[k], vs[(k + 1) % len(vs)]
                            key = (b2, a2) if a2 > b2 else (a2, b2)
                            counts.setdefault(key, []).append(p.index)
                    shown = 0
                    for key, faces in counts.items():
                        if len(faces) != 2 and shown < 8:
                            shown += 1
                            areas = [
                                f"{temp2.polygons[fi].area:.1e}"
                                for fi in faces
                            ]
                            _mark(
                                f"    edge {key} faces={len(faces)} "
                                f"newv={[vi >= n_orig for vi in key]} "
                                f"areas={areas}"
                            )
                bpy.data.meshes.remove(temp2)

            t0 = time.perf_counter()
            st = bpy.ops.rigo.region_apply()
            _mark(
                f"  operator: {st} {time.perf_counter() - t0:.1f}s "
                f"refined_added={region.refined_added}"
            )
            # Independent post-commit rim forensics: is the SHIPPED mesh
            # torn (self-intersections, folded flaps, flipped shards), or
            # clean geometry that only the raw preview / shading shows torn?
            me2 = obj.data
            wpost = {}
            vg = obj.vertex_groups.get(region.surface_mask)
            for v in me2.vertices:
                for g in v.groups:
                    if g.group == vg.index:
                        wpost[v.index] = g.weight
                        break
            member2 = {i for i, w in wpost.items() if w > 0.0}
            affected2 = [
                p for p in me2.polygons
                if any(vi in member2 for vi in p.vertices)
            ]
            selfx = ro._footprint_self_intersections(me2, member2, affected2)
            by_edge = {}
            for p in affected2:
                vs = p.vertices
                for k in range(len(vs)):
                    a, b = vs[k], vs[(k + 1) % len(vs)]
                    key = (b, a) if a > b else (a, b)
                    by_edge.setdefault(key, []).append(p.index)
            folded = 0
            worst_dot = 1.0
            for key, faces in by_edge.items():
                if len(faces) == 2:
                    d = me2.polygons[faces[0]].normal.dot(
                        me2.polygons[faces[1]].normal
                    )
                    worst_dot = min(worst_dot, d)
                    if d < -0.5:
                        folded += 1
            tiny = sum(1 for p in affected2 if p.area < 1e-10)
            nonman = ro._nonmanifold_count(me2)
            _mark(
                f"  committed-rim forensics: selfx={len(selfx)} "
                f"folded(dot<-0.5)={folded} worst_dot={worst_dot:.2f} "
                f"tiny_faces={tiny} nonman={nonman}"
            )
            bpy.data.objects.remove(obj, do_unlink=True)
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
