"""#49e evidence: is the residual radial-pleat crown in the feather wall a
MESH problem or a FIELD problem?

The falloff weight is baked in ``_region_weights_from_selection`` as an
edge-walk Dijkstra distance from the painted rim VERTICES.  Two properties of
that construction are suspected:

  (a) metrication  — graph distance overestimates true geodesic distance
      anisotropically (path must follow edges), and
  (b) creases      — a distance field measured from a jagged rim is only C0:
      its gradient jumps along the medial bisectors between adjacent rim
      seeds, one crease per reflex corner of the rim.  Refining the mesh
      reproduces those creases MORE faithfully; it cannot remove them.

Decisive test: displace the SAME tessellation with four different fields and
measure the wall dihedral spectrum.  Tessellation, amount, feather, falloff
curve, displacement direction and repair are identical in all four arms, so
any difference in the wall is attributable to the field alone.

  dij     production Dijkstra-from-rim-vertices
  ref     exact Euclidean distance to the rim POLYLINE (segments, not
          vertices).  Over a 15 mm band on a ~150 mm-radius torso the
          geodesic/Euclidean gap is d^3/24R^2 ~ 0.006 mm, so this is a
          near-exact geodesic reference AND it is crease-free except at
          reflex corners of the rim.
  refsm   same, but distance to a Laplacian-smoothed rim polyline — isolates
          how much of the crown is the jagged authored boundary itself.
  moll    production Dijkstra field mollified by K Jacobi passes with the rim
          pinned at 0 — the cheapest candidate production fix.

Stage 2 repeats ref/refsm on the REFINED commit mesh, where the production
field is frozen (originals are hard anchors for the harmonic pass), to show
whether re-evaluating the authored boundary at refined density helps.

Evidence only — writes fielddbg_result.txt, changes nothing.
"""

import importlib
import math
import os
import sys
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import A_SCAN  # noqa: E402

_OUT = r"C:\Projects\Blender Add-on Braces\fielddbg_result.txt"
_TRIES = {"n": 0}
_log = []

AMOUNT_MM = 20.0
FEATHER_MM = 15.0
PATCH_R = 0.059


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


# ----------------------------------------------------------------------------
# reference distance: exact Euclidean distance to a polyline
# ----------------------------------------------------------------------------
def _seg_dist(p, a, b):
    ab = b - a
    denom = ab.length_squared
    if denom < 1e-18:
        return (p - a).length
    t = (p - a).dot(ab) / denom
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return (p - (a + ab * t)).length


def _rim_segments(me, weights, rim):
    """Edges of the mesh whose both endpoints are rim (w == 0) vertices and
    that bound the weighted patch — the authored boundary polyline."""
    segs = []
    for e in me.edges:
        a, b = e.vertices
        if a in rim and b in rim:
            segs.append((me.vertices[a].co.copy(), me.vertices[b].co.copy()))
    return segs


def _smooth_rim(me, rim, passes=6):
    """Laplacian-smooth the rim polyline in place (probe only): each rim
    vertex averaged with its rim neighbours."""
    nbr = {i: [] for i in rim}
    for e in me.edges:
        a, b = e.vertices
        if a in rim and b in rim:
            nbr[a].append(b)
            nbr[b].append(a)
    pos = {i: me.vertices[i].co.copy() for i in rim}
    for _ in range(passes):
        new = {}
        for i in rim:
            ns = nbr[i]
            if len(ns) < 2:
                new[i] = pos[i]
                continue
            mean = Vector()
            for j in ns:
                mean += pos[j]
            mean /= len(ns)
            new[i] = pos[i].lerp(mean, 0.5)
        pos = new
    segs = []
    for i in rim:
        for j in nbr[i]:
            if j > i:
                segs.append((pos[i], pos[j]))
    return segs


def _dist_to_segments(co, segs):
    best = 1e30
    for a, b in segs:
        d = _seg_dist(co, a, b)
        if d < best:
            best = d
    return best


def _falloff_field(dist, f_eff, ro):
    return {
        i: ro._falloff(min(d, f_eff) / f_eff, "SMOOTH") if f_eff > 1e-9 else 1.0
        for i, d in dist.items()
    }


def _mollify(dist, adjacency, rim, passes=12, lam=0.5):
    """Jacobi low-pass of the distance field with the rim pinned at 0."""
    cur = dict(dist)
    for _ in range(passes):
        nxt = {}
        for i, d in cur.items():
            if i in rim:
                nxt[i] = 0.0
                continue
            ns = adjacency.get(i, ())
            if not ns:
                nxt[i] = d
                continue
            mean = sum(cur.get(j, d) for j in ns) / len(ns)
            nxt[i] = d + lam * (mean - d)
        cur = nxt
    return cur


# ----------------------------------------------------------------------------
# wall quality of a displaced copy
# ----------------------------------------------------------------------------
def _candidate_field(me, sel, rim, adj, f_eff, mean_edge):
    """The PROPOSED production formulation, verbatim, so stage 3 measures the
    real thing:

      1. mollify the rim POLYLINE (Laplacian along the rim) — kills the
         per-vertex jaggedness the paint tool quantized in, keeps the authored
         oval (low Fourier modes are untouched: measured below).
      2. multi-source Dijkstra from the rim, tracking each vertex's ROOT rim
         vertex — this is the intrinsic, surface-walking part.
      3. distance = exact point-to-SEGMENT distance, but only to rim segments
         within 3 rim-steps of that root.  Euclidean measurement gated by a
         geodesic neighbourhood: over ~12 mm on a ~120 mm-radius torso the
         chord/arc gap is d^3/24R^2 ~ 0.005 mm, and no far-side shortcut is
         reachable because the root came from a surface walk.
      4. re-zero the level set onto the rim (subtract the rim's own median
         residual) and pin the rim itself at 0 so the region edge still
         lands exactly on the untouched scan.
    """
    import heapq

    rim_nbr = {i: [] for i in rim}
    for e in me.edges:
        a, b = e.vertices
        if a in rim and b in rim:
            rim_nbr[a].append(b)
            rim_nbr[b].append(a)

    pos = {i: me.vertices[i].co.copy() for i in rim}
    orig = {i: p.copy() for i, p in pos.items()}
    for _ in range(6):
        new = {}
        for i in rim:
            ns = rim_nbr[i]
            if len(ns) < 2:
                new[i] = pos[i]
                continue
            mean = Vector()
            for j in ns:
                mean += pos[j]
            new[i] = pos[i].lerp(mean / len(ns), 0.5)
        pos = new
    moved = sorted((pos[i] - orig[i]).length * 1000.0 for i in rim)

    depth = {i: 0.0 for i in rim}
    root = {i: i for i in rim}
    heap = [(0.0, i) for i in rim]
    heapq.heapify(heap)
    while heap:
        d, i = heapq.heappop(heap)
        if d > depth.get(i, 1e30):
            continue
        for j in adj.get(i, ()):
            nd = d + (me.vertices[i].co - me.vertices[j].co).length
            if nd < depth.get(j, 1e30):
                depth[j] = nd
                root[j] = root[i]
                heapq.heappush(heap, (nd, j))

    near = {}
    for r in rim:
        ring = {r}
        frontier = [r]
        for _ in range(3):
            nxt = []
            for v in frontier:
                for n in rim_nbr[v]:
                    if n not in ring:
                        ring.add(n)
                        nxt.append(n)
            frontier = nxt
        segs = []
        for v in ring:
            for n in rim_nbr[v]:
                if n in ring and n > v:
                    segs.append((pos[v], pos[n]))
        near[r] = segs

    raw = {}
    for i in sel:
        r = root.get(i)
        segs = near.get(r) if r is not None else None
        if not segs:
            raw[i] = depth.get(i, f_eff)
            continue
        co = me.vertices[i].co
        raw[i] = min(_seg_dist(co, a, b) for a, b in segs)

    resid = sorted(raw[i] for i in rim)
    r0 = resid[len(resid) // 2] if resid else 0.0
    dist = {}
    for i in sel:
        dist[i] = 0.0 if i in rim else max(0.0, raw[i] - r0)
    diag = (
        f"rim_smoothing_shift mean={sum(moved)/len(moved):.2f}mm "
        f"p95={moved[int(len(moved)*0.95)]:.2f}mm max={moved[-1]:.2f}mm "
        f"(mean_edge={mean_edge*1000:.2f}mm) | rim residual re-zero "
        f"r0={r0*1000:.2f}mm p95={resid[int(len(resid)*0.95)]*1000:.2f}mm"
    )
    return dist, diag


def _wall_metrics(me, weights):
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
    if not angles:
        return "wall_edges=0"
    p95 = angles[int(len(angles) * 0.95)]
    return (
        f"wall_edges={len(angles)} dih_mean={sum(angles)/len(angles):.1f} "
        f"p95={p95:.1f} max={angles[-1]:.1f} "
        f">30deg={sum(1 for a in angles if a > 30.0)} "
        f"ridges={len(ridges)} ridge_max={max(ridges) if ridges else 0.0:.1f}"
    )


def _grad_kink(me, weights):
    """p95 angle between the per-face gradients of w across band edges.

    A crease in the field is a gradient DIRECTION jump; the mesh curvature
    contributes the same bias to every arm, so the arms are comparable.
    """
    grads = {}
    for p in me.polygons:
        vs = list(p.vertices)
        if len(vs) != 3:
            continue
        ws = [weights.get(i, 0.0) for i in vs]
        if max(ws) <= 0.02 or min(ws) >= 0.98:
            continue
        p0, p1, p2 = (me.vertices[i].co for i in vs)
        n = p.normal
        area2 = 2.0 * p.area
        if area2 < 1e-12:
            continue
        g = (
            n.cross(p2 - p1) * ws[0]
            + n.cross(p0 - p2) * ws[1]
            + n.cross(p1 - p0) * ws[2]
        ) / area2
        if g.length > 1e-9:
            grads[p.index] = g
    by_edge = {}
    for fi in grads:
        vs = me.polygons[fi].vertices
        for k in range(len(vs)):
            a, b = vs[k], vs[(k + 1) % len(vs)]
            key = (b, a) if a > b else (a, b)
            by_edge.setdefault(key, []).append(fi)
    kinks = []
    for faces in by_edge.values():
        if len(faces) != 2:
            continue
        g1, g2 = grads[faces[0]], grads[faces[1]]
        c = g1.normalized().dot(g2.normalized())
        c = max(-1.0, min(1.0, c))
        kinks.append(math.degrees(math.acos(c)))
    if not kinks:
        return "kink_n=0"
    kinks.sort()
    return (
        f"kink_n={len(kinks)} mean={sum(kinks)/len(kinks):.1f} "
        f"p95={kinks[int(len(kinks)*0.95)]:.1f} max={kinks[-1]:.1f} "
        f">30deg={sum(1 for a in kinks if a > 30.0)}"
    )


def _displace_copy(ro, src_me, weights, offset, label):
    """Displace a copy of src_me by offset*w along faired normals (the exact
    production displacement, no repair) and report the wall."""
    temp = src_me.copy()
    member = {i for i, w in weights.items() if w > 0.0}
    total = count = 0.0
    for e in temp.edges:
        a, b = e.vertices
        if a in member or b in member:
            total += (temp.vertices[a].co - temp.vertices[b].co).length
            count += 1
    mean_edge = total / count if count else 0.001
    faired, _adj = ro._faired_normals(temp, weights, mean_edge)
    for i in faired:
        temp.vertices[i].co += faired[i] * (offset * weights[i])
    temp.update()
    _mark(f"    {label:<7} {_wall_metrics(temp, weights)}")
    bpy.data.meshes.remove(temp)


def _adjacency(me, keys):
    adj = {i: [] for i in keys}
    for e in me.edges:
        a, b = e.vertices
        if a in adj and b in adj:
            adj[a].append(b)
            adj[b].append(a)
    return adj


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    ro = importlib.import_module(
        "bl_ext.user_default.rigo_brace.operators.region_ops"
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
        z_min = min(c.z for c in cos)
        z_max = max(c.z for c in cos)
        y_min, y_max = min(c.y for c in cos), max(c.y for c in cos)
        x_min, x_max = min(c.x for c in cos), max(c.x for c in cos)
        target = Vector((
            (x_min + x_max) * 0.5,
            y_min + 0.10 * (y_max - y_min),
            z_min + 0.45 * (z_max - z_min),
        ))
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
            if (f.calc_center_median() - center).length < PATCH_R:
                f.select = True
        bmesh.update_edit_mesh(me)

        # the production bake, called directly
        weights, _c, _n, _r = ro._region_weights_from_selection(
            obj, FEATHER_MM, "SMOOTH"
        )
        bpy.ops.object.mode_set(mode="OBJECT")

        offset = -AMOUNT_MM * 0.001
        rim = {i for i, w in weights.items() if w <= 0.0}
        sel = set(weights)
        adj = _adjacency(me, sel)

        # recover the Dijkstra distance the bake used (same recurrence)
        import heapq
        depth = {i: 0.0 for i in rim}
        heap = [(0.0, i) for i in rim]
        heapq.heapify(heap)
        while heap:
            d, i = heapq.heappop(heap)
            if d > depth.get(i, 1e30):
                continue
            for j in adj[i]:
                nd = d + (me.vertices[i].co - me.vertices[j].co).length
                if nd < depth.get(j, 1e30):
                    depth[j] = nd
                    heapq.heappush(heap, (nd, j))
        max_depth = max(depth.values())
        f_eff = min(FEATHER_MM * 0.001, max_depth)
        d_dij = {i: depth.get(i, max_depth) for i in sel}

        segs = _rim_segments(me, weights, rim)
        segs_sm = _smooth_rim(me, rim)
        d_ref = {i: _dist_to_segments(me.vertices[i].co, segs) for i in sel}
        d_refsm = {
            i: _dist_to_segments(me.vertices[i].co, segs_sm) for i in sel
        }
        d_moll = _mollify(d_dij, adj, rim)

        band = [i for i in sel if 0.0 < d_dij[i] < f_eff]
        over = [
            (d_dij[i] - d_ref[i]) / max(d_ref[i], 1e-6)
            for i in band if d_ref[i] > 0.002
        ]
        over.sort()
        edge_len = sum(
            (me.vertices[a].co - me.vertices[b].co).length
            for a, b in ((e.vertices[0], e.vertices[1]) for e in me.edges)
            if a in sel and b in sel
        ) / max(1, sum(
            1 for e in me.edges
            if e.vertices[0] in sel and e.vertices[1] in sel
        ))

        _mark(
            f"PATCH sel_verts={len(sel)} rim_verts={len(rim)} "
            f"rim_segments={len(segs)} band_verts={len(band)} "
            f"mean_edge={edge_len*1000:.2f}mm feather={f_eff*1000:.2f}mm "
            f"rings_across_feather={f_eff/edge_len:.1f}"
        )
        if over:
            _mark(
                f"DIJKSTRA vs EXACT distance over the band: "
                f"mean_overestimate={sum(over)/len(over)*100:.1f}% "
                f"p95={over[int(len(over)*0.95)]*100:.1f}% "
                f"max={over[-1]*100:.1f}%  "
                f"(a {sum(over)/len(over)*100:.0f}% distance error at the "
                f"steepest point of smoothstep moves the wall by "
                f"{1.5*(sum(over)/len(over))*AMOUNT_MM:.1f}mm)"
            )

        d_cand, cand_diag = _candidate_field(me, sel, rim, adj, f_eff, edge_len)
        _mark(f"CANDIDATE bounds: {cand_diag}")

        fields = {
            "dij": _falloff_field(d_dij, f_eff, ro),
            "ref": _falloff_field(d_ref, f_eff, ro),
            "refsm": _falloff_field(d_refsm, f_eff, ro),
            "moll": _falloff_field(d_moll, f_eff, ro),
            "cand": _falloff_field(d_cand, f_eff, ro),
            "new": weights,  # whatever the INSTALLED bake now produces
        }
        _mark("")
        _mark("STAGE 1 — ORIGINAL tessellation, four fields, same everything")
        for name, w in fields.items():
            _mark(f"  {name}: {_grad_kink(me, w)}")
        for name, w in fields.items():
            _displace_copy(ro, me, w, offset, name)

        # --------------------------------------------------------------
        # STAGE 2 — the shipping path: refined mesh
        # --------------------------------------------------------------
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = AMOUNT_MM
        settings.region_feather = FEATHER_MM
        settings.region_falloff = "SMOOTH"
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.rigo.region_add()
        bpy.ops.object.mode_set(mode="OBJECT")
        region = obj.rigo_regions[obj.rigo_region_index]
        group = obj.vertex_groups.get(region.surface_mask)

        rim_field = None
        if hasattr(ro, "_authored_rim_field"):
            rim_field = ro._authored_rim_field(
                me, group.index, region.falloff_type
            )
        _mark(f"  authored rim field recovered: {rim_field is not None}")
        temp = me.copy()
        added, tgt = ro._refine_footprint(
            temp, group.index, offset, field=rim_field
        )
        w_prod = {}
        for v in temp.vertices:
            for g in v.groups:
                if g.group == group.index:
                    w_prod[v.index] = g.weight
                    break
        sel2 = set(w_prod)
        d_ref2 = {i: _dist_to_segments(temp.vertices[i].co, segs) for i in sel2}
        d_refsm2 = {
            i: _dist_to_segments(temp.vertices[i].co, segs_sm) for i in sel2
        }
        w_ref2 = _falloff_field(d_ref2, f_eff, ro)
        w_refsm2 = _falloff_field(d_refsm2, f_eff, ro)
        adj2 = _adjacency(temp, sel2)
        rim2 = {i for i in sel2 if w_prod[i] <= 0.0}
        d_prod2 = {
            i: f_eff * (1.0 if w_prod[i] >= 1.0 else _inv_smoothstep(w_prod[i]))
            for i in sel2
        }
        w_moll2 = _falloff_field(
            _mollify(d_prod2, adj2, rim2, passes=24), f_eff, ro
        )

        _mark("")
        _mark(
            f"STAGE 2 — REFINED tessellation (+{added} verts, "
            f"target {tgt:.2f}mm), field re-evaluated from the SAME "
            f"authored rim"
        )
        for name, w in (
            ("prod", w_prod), ("ref", w_ref2),
            ("refsm", w_refsm2), ("moll", w_moll2),
        ):
            _mark(f"  {name}: {_grad_kink(temp, w)}")
        for name, w in (
            ("prod", w_prod), ("ref", w_ref2),
            ("refsm", w_refsm2), ("moll", w_moll2),
        ):
            _displace_copy(ro, temp, w, offset, name)

        # profile fidelity: does a candidate still realize the authored
        # smoothstep against TRUE distance?
        _mark("")
        _mark("PROFILE fidelity vs exact distance (refined band):")
        for name, w in (
            ("prod", w_prod), ("ref", w_ref2),
            ("refsm", w_refsm2), ("moll", w_moll2),
        ):
            err = []
            for i in sel2:
                t = min(d_ref2[i], f_eff) / f_eff
                err.append(abs(w[i] - ro._falloff(t, "SMOOTH")))
            err.sort()
            _mark(
                f"  {name:<6} mean_dev={sum(err)/len(err):.3f} "
                f"p95={err[int(len(err)*0.95)]:.3f} max={err[-1]:.3f} "
                f"(x{AMOUNT_MM:.0f}mm -> "
                f"{err[int(len(err)*0.95)]*AMOUNT_MM:.2f}mm p95 shift)"
            )

        bpy.data.meshes.remove(temp)

        # --------------------------------------------------------------
        # STAGE 3 — production prediction: bake the CANDIDATE field on the
        # ORIGINAL vertices (as region_add would), then run the real
        # refinement, which interpolates it with IDW + the harmonic pass.
        # This is what would actually ship.
        # --------------------------------------------------------------
        w_cand = fields["cand"]
        for i in sel:
            group.add([i], w_cand[i], "REPLACE")
        temp3 = me.copy()
        added3, tgt3 = ro._refine_footprint(temp3, group.index, offset)
        w3 = {}
        for v in temp3.vertices:
            for g in v.groups:
                if g.group == group.index:
                    w3[v.index] = g.weight
                    break
        _mark("")
        _mark(
            f"STAGE 3 — CANDIDATE baked at region_add, then the real "
            f"refinement (+{added3} verts, target {tgt3:.2f}mm)"
        )
        _mark(f"  cand: {_grad_kink(temp3, w3)}")
        _displace_copy(ro, temp3, w3, offset, "cand")
        d_ref3 = {i: _dist_to_segments(temp3.vertices[i].co, segs) for i in w3}
        err = sorted(
            abs(w3[i] - ro._falloff(min(d_ref3[i], f_eff) / f_eff, "SMOOTH"))
            for i in w3
        )
        _mark(
            f"  profile vs exact-distance smoothstep: "
            f"mean_dev={sum(err)/len(err):.3f} "
            f"p95={err[int(len(err)*0.95)]:.3f} "
            f"(x{AMOUNT_MM:.0f}mm -> {err[int(len(err)*0.95)]*AMOUNT_MM:.2f}mm)"
        )
        outside = max(
            (w3[i] for i in w3 if i in rim), default=0.0
        )
        _mark(
            f"  rim weight after bake: max={outside:.5f} "
            f"-> {outside*AMOUNT_MM:.3f}mm lift at the region edge"
        )
        bpy.data.meshes.remove(temp3)
        _mark("")
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        bpy.ops.wm.quit_blender()
    return None


def _inv_smoothstep(y):
    """Invert smoothstep numerically (bisection) — recovers the normalized
    distance a production weight corresponds to."""
    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = (lo + hi) * 0.5
        if mid * mid * (3.0 - 2.0 * mid) < y:
            lo = mid
        else:
            hi = mid
    return (lo + hi) * 0.5


bpy.app.timers.register(_run, first_interval=0.5)
