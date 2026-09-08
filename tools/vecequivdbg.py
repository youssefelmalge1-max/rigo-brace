"""#53 — are the numpy whole-mesh scans bit-identical to the loops they replaced?

On a real painted region (A scan, RIGO_SUBDIV=0|1), before AND after the
commit, compares the shipped helpers against VERBATIM copies of the pre-#53
bodies:

  _faces_by_membership   vs  the two `any(vi in member ...)` list comprehensions
  _mean_touching_edge    vs  the edge loop (float equality, not tolerance)
  _faired_normals        vs  old body (faired vectors exact, adjacency exact)
  _tri_bvh               vs  old fan loop (verts, polys, owner indices)
  _footprint_self_intersections / _static_faces_bvh  vs  old bodies
  _nonmanifold_count     vs  old body

Also times each pair.  Writes vecequivdbg_L<n>_result.txt with
VEC_EQUIVALENT=True/False.  GUI Blender only.
"""

import heapq
import os
import sys
import time
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import A_SCAN  # noqa: E402

LEVELS = int(os.environ.get("RIGO_SUBDIV", "0"))
ROOT = r"C:\Projects\Blender Add-on Braces"
OUT = os.path.join(ROOT, f"vecequivdbg_L{LEVELS}_result.txt")
AMOUNT_MM = 15.0
FEATHER_MM = 10.0
PATCH_R = 0.045
TRIES = {"n": 0}
LOG = []
FAILS = []


def _log(msg):
    LOG.append(str(msg))
    print("[vecequiv]", msg)


# ----------------------------- OLD bodies (verbatim) ----------------------- #
def old_tri_bvh(me, faces):
    if not faces:
        return None, [], []
    used = sorted({vi for p in faces for vi in p.vertices})
    local = {vi: n for n, vi in enumerate(used)}
    verts = [me.vertices[vi].co.copy() for vi in used]
    polys = []
    owner = []
    for poly in faces:
        idx = [local[vi] for vi in poly.vertices]
        for k in range(1, len(idx) - 1):
            polys.append((idx[0], idx[k], idx[k + 1]))
            owner.append(poly)
    if not polys:
        return None, [], []
    return BVHTree.FromPolygons(verts, polys, all_triangles=True), owner, polys


def old_footprint_self_intersections(me, member, faces=None):
    if faces is None:
        faces = [
            p for p in me.polygons if any(vi in member for vi in p.vertices)
        ]
    tree, owner, polys = old_tri_bvh(me, faces)
    if tree is None:
        return set()
    bad = set()
    for a, b in tree.overlap(tree):
        if a == b or owner[a] is owner[b]:
            continue
        if set(polys[a]) & set(polys[b]):
            continue
        bad.add(owner[a].index)
        bad.add(owner[b].index)
    return bad


def old_static_faces(me, member):
    return [
        p for p in me.polygons if not any(vi in member for vi in p.vertices)
    ]


def old_affected(me, member):
    return [p for p in me.polygons if any(vi in member for vi in p.vertices)]


def old_mean_edge(me, member):
    edge_total = 0.0
    edge_count = 0
    for e in me.edges:
        a, b = e.vertices
        if a in member or b in member:
            edge_total += (me.vertices[a].co - me.vertices[b].co).length
            edge_count += 1
    return edge_total / edge_count if edge_count else None


def old_faired_normals(me, weights, mean_edge):
    radius = max(0.006, 2.0 * mean_edge)
    member = {i for i, w in weights.items() if w > 0.0}
    ring1 = set(member)
    for edge in me.edges:
        a, b = edge.vertices
        if a in member or b in member:
            ring1.add(a)
            ring1.add(b)
    adjacency = {}
    for edge in me.edges:
        a, b = edge.vertices
        if a in ring1 or b in ring1:
            adjacency.setdefault(a, []).append(b)
            adjacency.setdefault(b, []).append(a)
    faired = {}
    for i in member:
        dist = {i: 0.0}
        heap = [(0.0, i)]
        accumulated = Vector()
        while heap:
            d, j = heapq.heappop(heap)
            if d > dist.get(j, 1e30):
                continue
            accumulated += me.vertices[j].normal
            for k in adjacency.get(j, ()):
                nd = d + (me.vertices[j].co - me.vertices[k].co).length
                if nd <= radius and nd < dist.get(k, 1e30):
                    dist[k] = nd
                    heapq.heappush(heap, (nd, k))
        if accumulated.length < 1e-9:
            accumulated = me.vertices[i].normal.copy()
        faired[i] = accumulated.normalized()
    return faired, adjacency


def old_nonmanifold_count(me):
    counts = [0] * len(me.edges)
    edge_indices = [0] * len(me.loops)
    me.loops.foreach_get("edge_index", edge_indices)
    for i in edge_indices:
        counts[i] += 1
    return sum(1 for c in counts if c != 2)


# ------------------------------------------------------------------------- #
def _check(name, ok, detail=""):
    _log(f"{'ok  ' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        FAILS.append(name)


def _timed(fn, *args):
    t0 = time.perf_counter()
    out = fn(*args)
    return out, time.perf_counter() - t0


def _weights_of(me, group_index):
    weights = {}
    for v in me.vertices:
        for g in v.groups:
            if g.group == group_index:
                weights[v.index] = g.weight
                break
    return weights


def _compare(region_ops, me, group_index, tag):
    weights = _weights_of(me, group_index)
    member = {i for i, w in weights.items() if w > 0.0}
    _log(f"[{tag}] verts={len(me.vertices)} faces={len(me.polygons)} "
         f"member={len(member)} weighted={len(weights)}")

    (with_new, without_new), t_new = _timed(region_ops._faces_by_membership, me, member)
    with_old, t_a = _timed(old_affected, me, member)
    without_old, t_b = _timed(old_static_faces, me, member)
    _check(f"{tag}.affected_faces",
           [p.index for p in with_new] == [p.index for p in with_old],
           f"n={len(with_new)} new={t_new:.3f}s old={t_a + t_b:.3f}s")
    _check(f"{tag}.static_faces",
           [p.index for p in without_new] == [p.index for p in without_old],
           f"n={len(without_new)}")

    m_new, t_new = _timed(region_ops._mean_touching_edge, me, member)
    m_old, t_old = _timed(old_mean_edge, me, member)
    _check(f"{tag}.mean_edge_member", m_new == m_old,
           f"{m_new!r} vs {m_old!r} new={t_new:.3f}s old={t_old:.3f}s")
    m_new = region_ops._mean_touching_edge(me, weights)
    m_old = old_mean_edge(me, weights)
    _check(f"{tag}.mean_edge_weighted", m_new == m_old, f"{m_new!r} vs {m_old!r}")

    mean_edge = m_old if m_old is not None else 0.003
    (f_new, adj_new), t_new = _timed(region_ops._faired_normals, me, weights, mean_edge)
    (f_old, adj_old), t_old = _timed(old_faired_normals, me, weights, mean_edge)
    same_keys = set(f_new) == set(f_old)
    same_vals = same_keys and all(tuple(f_new[k]) == tuple(f_old[k]) for k in f_old)
    _check(f"{tag}.faired_normals", same_vals,
           f"n={len(f_new)} new={t_new:.3f}s old={t_old:.3f}s")
    _check(f"{tag}.faired_adjacency", adj_new == adj_old, f"n={len(adj_new)}")

    for label, faces in (("affected", with_old), ("static", without_old)):
        (tree_n, own_n, pol_n), t_new = _timed(region_ops._tri_bvh, me, faces)
        (tree_o, own_o, pol_o), t_old = _timed(old_tri_bvh, me, faces)
        _check(f"{tag}.tri_bvh_{label}_polys",
               [tuple(p) for p in pol_n] == [tuple(p) for p in pol_o],
               f"n={len(pol_n)} new={t_new:.3f}s old={t_old:.3f}s")
        _check(f"{tag}.tri_bvh_{label}_owner",
               [p.index for p in own_n] == [p.index for p in own_o])
        if tree_n is not None and tree_o is not None:
            ov_n = sorted(tuple(sorted(p)) for p in tree_n.overlap(tree_n))
            ov_o = sorted(tuple(sorted(p)) for p in tree_o.overlap(tree_o))
            _check(f"{tag}.tri_bvh_{label}_overlap", ov_n == ov_o,
                   f"pairs={len(ov_n)}")

    bad_n, t_new = _timed(region_ops._footprint_self_intersections, me, member)
    bad_o, t_old = _timed(old_footprint_self_intersections, me, member)
    _check(f"{tag}.self_intersections", bad_n == bad_o,
           f"n={len(bad_n)} new={t_new:.3f}s old={t_old:.3f}s")

    n_new, t_new = _timed(region_ops._nonmanifold_count, me)
    n_old, t_old = _timed(old_nonmanifold_count, me)
    _check(f"{tag}.nonmanifold", n_new == n_old,
           f"{n_new} vs {n_old} new={t_new:.3f}s old={t_old:.3f}s")


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 60:
        return 0.25
    try:
        import importlib
        region_ops = importlib.import_module(
            "bl_ext.user_default.rigo_brace.operators.region_ops"
        )
        from bl_ext.user_default.rigo_brace.operators.scan_ops import (  # noqa
            shade_smooth_scan,
        )
        settings = bpy.context.scene.rigo_brace
        bpy.ops.wm.stl_import(filepath=A_SCAN)
        obj = bpy.context.active_object
        settings.scan_object = obj
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        me = obj.data
        if LEVELS > 0:
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.subdivide(number_cuts=LEVELS, smoothness=1.0)
            bpy.ops.object.mode_set(mode="OBJECT")
            me = obj.data
            shade_smooth_scan(me)
        mw = obj.matrix_world
        cos = [mw @ v.co for v in me.vertices]
        lo = Vector((min(c.x for c in cos), min(c.y for c in cos), min(c.z for c in cos)))
        hi = Vector((max(c.x for c in cos), max(c.y for c in cos), max(c.z for c in cos)))
        kd = kdtree.KDTree(len(me.vertices))
        for v in me.vertices:
            kd.insert(mw @ v.co, v.index)
        kd.balance()
        _co, seed, _d = kd.find(Vector((
            (lo.x + hi.x) * 0.5,
            lo.y + 0.10 * (hi.y - lo.y),
            lo.z + 0.45 * (hi.z - lo.z),
        )))
        centre_local = me.vertices[seed].co.copy()
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(me)
        for f in bm.faces:
            if (f.calc_center_median() - centre_local).length < PATCH_R:
                f.select = True
        bmesh.update_edit_mesh(me)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = AMOUNT_MM
        settings.region_feather = FEATHER_MM
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add()
        region = obj.rigo_regions[obj.rigo_region_index]
        group = obj.vertex_groups.get(region.surface_mask)
        bpy.ops.object.mode_set(mode="OBJECT")
        _compare(region_ops, obj.data, group.index, "pre")
        result = bpy.ops.rigo.region_apply()
        _log(f"commit {result} refined_added={region.refined_added}")
        _compare(region_ops, obj.data, group.index, "post")
        _log(f"failed={FAILS}")
        _log(f"VEC_EQUIVALENT={not FAILS}")
    except Exception as error:  # noqa: BLE001
        _log(f"ERROR={error!r}\n{traceback.format_exc()}\nVEC_EQUIVALENT=False")
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(LOG) + "\n")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
