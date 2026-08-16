"""Contract-gated quality test for Pressure/Expansion regions + style library.

Implements knowledge/region_quality_contract.md (#48): validity, smoothness,
amount, feather, library parity, resolution robustness, evaluated-surface
consistency, determinism and performance — as hard PASS/FAIL gates, not
appearance.  Writes regionqualtest_result.txt (last line PASS=True/False).

GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools\regionqualtest.py
"""

import heapq
import math
import os
import random
import statistics
import subprocess
import sys
import time
import traceback

import bpy
import bmesh
import importlib
from mathutils import Vector, kdtree
from mathutils.bvhtree import BVHTree

# Every numeric gate value comes from the contract's machine-readable block —
# nowhere else (hardening Wave 0, DEC-0042).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quality_contract

_T = quality_contract.load()

_OUT = r"C:\Projects\Blender Add-on Braces\regionqualtest_result.txt"
_SCAN = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_A_SCAN = r"C:\Projects\Blender Add-on Braces\A type model.stl"
_PATIENT = r"C:\Projects\Blender Add-on Braces\A type model.stl"
_TRIES = {"n": 0}
_log = []
_GATES = {}
_STYLE_LABELS = (
    "QA Gate Scan Style", "QA Gate Scan Style5",
    "QA Gate Flat Style", "QA Gate Patient Style",
    "QA W2 Mirror Style", "QA W2 Source Style",
    "QA W2 HS Style", "QA W2 Size Style",
)


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _gate(name, ok, detail=""):
    _GATES[name] = bool(ok)
    _mark(f"GATE {name}={'ok' if ok else 'FAIL'} {detail}")


# --------------------------------------------------------------------------- #
# helpers (shared with regionqualdbg.py measurement machinery)
# --------------------------------------------------------------------------- #
def _import_scan(path):
    bpy.ops.wm.stl_import(filepath=path)
    obj = bpy.context.active_object
    settings = bpy.context.scene.rigo_brace
    settings.scan_object = obj
    bpy.context.view_layer.objects.active = obj
    settings.scan_units = "mm"
    bpy.ops.rigo.apply_units()
    return obj


def _delete(obj):
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:
        pass


def _adjacency(me):
    adj = [[] for _ in range(len(me.vertices))]
    for e in me.edges:
        a, b = e.vertices
        adj[a].append(b)
        adj[b].append(a)
    return adj


def _group_weights(obj, mask):
    vg = obj.vertex_groups.get(mask)
    if vg is None:
        return {}
    gi = vg.index
    out = {}
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == gi:
                out[v.index] = g.weight
                break
    return out


def _nonmanifold(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    n = sum(1 for e in bm.edges if not e.is_manifold)
    bm.free()
    return n


def _snapshot(obj):
    me = obj.data
    return (
        {v.index: v.co.copy() for v in me.vertices},
        {v.index: v.normal.copy() for v in me.vertices},
        {p.index: p.normal.copy() for p in me.polygons},
        [tuple(p.vertices) for p in me.polygons],
    )


def _topo_sig(me):
    """Topology signature: refusal oracles must prove the WHOLE state is
    untouched, not only the coordinates of pre-existing indices (#49: a
    leaked subdivision would otherwise pass a positions-only check)."""
    edge_hash = 0
    for e in me.edges:
        a, b = e.vertices
        edge_hash = (edge_hash * 1000003 + a * 65599 + b) & 0xFFFFFFFF
    return (len(me.vertices), len(me.edges), len(me.polygons), edge_hash)


def _refusal_untouched(obj, before, sig):
    return _topo_sig(obj.data) == sig and all(
        (obj.data.vertices[i].co - before[i]).length == 0.0 for i in before
    )


def _footprint_faces(me, fp):
    return [p for p in me.polygons if any(vi in fp for vi in p.vertices)]


def _dihedral_map(obj, fp):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    out = {}
    for e in bm.edges:
        if len(e.link_faces) != 2:
            continue
        if not any(v.index in fp for v in e.verts):
            continue
        key = (e.verts[0].index, e.verts[1].index)
        try:
            out[key] = math.degrees(abs(e.calc_face_angle()))
        except ValueError:
            out[key] = 180.0
    bm.free()
    return out


def _self_intersections(obj, fp):
    me = obj.data
    faces = _footprint_faces(me, fp)
    if not faces:
        return 0
    verts = [v.co for v in me.vertices]
    polys = [tuple(p.vertices) for p in faces]
    tree = BVHTree.FromPolygons(verts, polys, all_triangles=True)
    hits = set()
    for a, b in tree.overlap(tree):
        if a == b or set(polys[a]) & set(polys[b]):
            continue
        hits.add((min(a, b), max(a, b)))
    return len(hits)


def _cross_intersections(obj, fp):
    """Independent oracle for whole-body validity (Wave 1): footprint faces
    intersecting ANY non-footprint face of the mesh.

    Deliberately a different construction from the production predicate
    (whole-mesh tree vs production's static-only tree; global-index pair
    bookkeeping) so implementation and evidence cannot share a blind spot."""
    me = obj.data
    faces = _footprint_faces(me, fp)
    if not faces:
        return set()
    fpset = {p.index for p in faces}
    verts = [v.co for v in me.vertices]
    whole = BVHTree.FromPolygons(
        verts, [tuple(p.vertices) for p in me.polygons], all_triangles=True
    )
    fptree = BVHTree.FromPolygons(
        verts, [tuple(p.vertices) for p in faces], all_triangles=True
    )
    pairs = set()
    for a, b in fptree.overlap(whole):
        pa = faces[a]
        pb = me.polygons[b]
        if pa.index == pb.index or pb.index in fpset:
            continue
        if set(pa.vertices) & set(pb.vertices):
            continue
        pairs.add((pa.index, pb.index))
    return pairs


def _mean_edge_mm(me, fp):
    total = 0.0
    n = 0
    for e in me.edges:
        a, b = e.vertices
        if a in fp or b in fp:
            total += (me.vertices[a].co - me.vertices[b].co).length
            n += 1
    return (total / n * 1000.0) if n else 3.0


def _osc_gate_mm(amount_mm, feather_mm, h_mm):
    smooth = _T["smooth"]
    analytic = (
        2.0 * amount_mm * smooth["osc_profile_coeff"]
        / (feather_mm * feather_mm) * h_mm * h_mm
    )
    # Clamped so the bound can never go vacuous (it reached 40.5 mm at
    # feather 10): oscillation beyond the amount itself is never legitimate.
    return max(smooth["osc_floor_mm"], min(analytic, amount_mm))


def _measure(tag, obj, before, before_n, before_fn, pre_dih, weights,
             amount_mm, expect_sign, nonman0, pre_cross=frozenset(),
             pre_polys=None):
    me = obj.data
    adj = _adjacency(me)
    fp = {i for i, w in weights.items() if w > 1e-5}
    # Index-keyed displacement of the SURVIVING original vertices — parity
    # comparisons sample these probe points, matched by pre-position.
    d = {}
    for v in me.vertices:
        b = before.get(v.index)
        if b is not None:
            d[v.index] = (v.co - b).dot(before_n[v.index]) * 1000.0
    # Topology-independent displacement oracle (#49): signed distance of
    # EVERY post vertex (including refinement-born ones) to the pre-commit
    # surface — index maps cannot measure a refined commit.
    d_all = d
    surf = None
    # The BVH oracle set measures REFINED commits (index maps cannot);
    # unrefined commits keep the index oracles they were proven
    # behavior-neutral with — a refined-commit oracle applied to legacy
    # output flags the staircase legacy behavior was always accepted with.
    if pre_polys is not None and len(me.vertices) != len(before):
        pre_verts = [before[i] for i in range(len(before))]
        surf = BVHTree.FromPolygons(pre_verts, pre_polys, all_triangles=True)
        d_all = {}
        for v in me.vertices:
            loc, nor, _idx, _dist = surf.find_nearest(v.co)
            if loc is None:
                d_all[v.index] = 0.0
            else:
                d_all[v.index] = (v.co - loc).dot(nor) * 1000.0

    holes = 0
    for i in fp | {n for i in fp for n in adj[i]}:
        if weights.get(i, 0.0) < 0.1:
            if sum(1 for n in adj[i] if weights.get(n, 0.0) > 0.5) >= 3:
                holes += 1

    osc = []
    for i in fp:
        if i in d_all and adj[i]:
            known = [d_all[n] for n in adj[i] if n in d_all]
            if known:
                osc.append(abs(d_all[i] - sum(known) / len(known)))
    osc_max = max(osc) if osc else 0.0
    osc_mean = (sum(osc) / len(osc)) if osc else 0.0

    # Feather monotonicity on the INDEX-EXACT displacements of surviving
    # originals — the authored profile is defined on the authored samples.
    # The BVH signed distance misreads wrinkled zones by up to 2.1 mm
    # (measured: w 0.975/1.000 edge with exact d −14.61/−15.00 read as
    # −13.32/−12.93), so it must not vote on 0.2 mm-tolerance reversals;
    # new-vertex profile position stays covered by osc/decile/core on d_all.
    rev = 0
    rev_tol = _T["feather"]["rev_tol_mm"]
    for e in me.edges:
        a, b = e.vertices
        if a not in d or b not in d:
            continue
        wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
        if wa == wb or (wa == 0.0 and wb == 0.0):
            continue
        if (wa - wb) * (abs(d[a]) - abs(d[b])) < 0 \
                and abs(abs(d[a]) - abs(d[b])) > rev_tol:
            rev += 1

    core = [abs(d_all[i]) for i, w in weights.items()
            if w > 0.9 and i in d_all]
    core_med = statistics.median(core) if core else 0.0

    # Weight-decile profile: mean |d| must rise monotonically with weight
    # (shape-agnostic form of the contract's transition-profile clause).
    bins = {}
    for i, w in weights.items():
        if w > 0.0 and i in d_all:
            bins.setdefault(min(9, int(w * 10.0)), []).append(abs(d_all[i]))
    profile = [sum(v) / len(v) for _k, v in sorted(bins.items())]
    decile_tol = _T["feather"]["decile_rev_tol_mm"]
    decile_rev = sum(
        1 for a, b in zip(profile, profile[1:]) if b < a - decile_tol
    )

    # #49: commits may DECLARE refinement (vertices added inside the
    # footprint); shrinking is never legitimate.  The per-case
    # refined_declared gate pins the delta to the region's provenance.
    count_ok = (
        len(me.vertices) >= len(before)
        and len(me.polygons) >= len(before_fn)
    )
    outside = max(
        (abs(d_all[v.index]) for v in me.vertices
         if v.index not in weights and v.index in d_all),
        default=0.0,
    )
    sign_ok = all(
        (d_all[i] * expect_sign) >= -0.05
        for i in fp if i in d_all and abs(d_all[i]) > 0.1
    )

    post_dih = _dihedral_map(obj, fp)
    # Only PRE-EXISTING edges can prove commit damage; edges born from
    # refinement have no pre state (a wrinkled scan sampled finer shows
    # sharp dihedrals that were always there) — geometry of new edges is
    # covered by the quality gates.
    new_spikes = sum(
        1 for key, a in post_dih.items()
        if a > 60.0 and key in pre_dih and pre_dih[key] <= 45.0
    )
    # Fold oracle (Wave 1): a shared edge folded nearly shut that was not
    # even close before — measured in dihedral DEGREES, independent of the
    # production predicate's normal-dot construction.
    folds = sum(
        1 for key, a in post_dih.items()
        if a > _T["fold"]["oracle_post_deg"]
        and pre_dih.get(key) is not None
        and pre_dih[key] < _T["fold"]["oracle_pre_deg"]
    )
    new_cross = len(_cross_intersections(obj, fp) - set(pre_cross))
    # Inverted oracle: face indices reshuffle under refinement.  The robust
    # pre-orientation reference is the face's own ORIGINAL vertices'
    # pre-normals (crease-consistent); a nearest-surface normal can land on
    # the opposite wall of a crease 15 mm away and false-flag a legitimate
    # wall face.  All-new faces fall back to the BVH normal.
    if surf is not None:
        # A face counts inverted only when TWO independent references agree
        # (its original vertices' pre-normals AND the pre-surface normal at
        # its center): on creases the references legitimately disagree and
        # orientation is undefined — those faces are covered by the
        # selfx/fold predicates.  ALL-NEW faces (#49b) have no vertex
        # reference and the BVH surface normal alone is unreliable over
        # wrinkles (nearest pre-surface point lands on another fold flank —
        # measured up to 2 mm displacement misread), so their second
        # confirmation is a REAL fold against an edge-neighbour (< −0.5):
        # a genuinely inverted patch cannot exist without one — its rim
        # faces carry original vertices and its boundary must fold.
        nbr_faces = {}
        for p in _footprint_faces(me, fp):
            vs = p.vertices
            for k in range(len(vs)):
                a, b = vs[k], vs[(k + 1) % len(vs)]
                key = (a, b) if a < b else (b, a)
                nbr_faces.setdefault(key, []).append(p.index)
        inverted = 0
        for p in _footprint_faces(me, fp):
            reference = Vector()
            for vi in p.vertices:
                n = before_n.get(vi)
                if n is not None:
                    reference += n
            center = Vector()
            for vi in p.vertices:
                center += me.vertices[vi].co
            center /= len(p.vertices)
            _loc, nor, _idx, _dist = surf.find_nearest(center)
            # Confident agreement only (#49d): a REAL inversion measures
            # near −1 against both references (the pre-fix wreckage class);
            # dots within ±0.2 on decimated wrinkle flanks are reference
            # noise (measured: an all-original feather-rim face at
            # −0.16/−0.09 with no fold and no selfx tipped either way on
            # unrelated commit changes).
            by_verts = (
                reference.length >= 1.5
                and p.normal.dot(reference.normalized()) < -0.2
            )
            by_surf = nor is not None and p.normal.dot(nor) < -0.2
            if reference.length >= 1.5 and nor is not None:
                if by_verts and by_surf:
                    inverted += 1
            elif reference.length < 1e-9 and by_surf:
                vs = p.vertices
                folded_nbr = False
                for k in range(len(vs)):
                    a, b = vs[k], vs[(k + 1) % len(vs)]
                    key = (a, b) if a < b else (b, a)
                    for q in nbr_faces.get(key, ()):
                        if q != p.index and me.polygons[q].normal.dot(
                                p.normal) < -0.5:
                            folded_nbr = True
                if folded_nbr:
                    inverted += 1
            elif by_verts:
                inverted += 1
    else:
        inverted = sum(
            1 for p in _footprint_faces(me, fp)
            if p.index in before_fn and p.normal.dot(before_fn[p.index]) < 0.0
        )
    degen = sum(1 for p in _footprint_faces(me, fp) if p.area < 1e-12)
    selfx = _self_intersections(obj, fp)
    nonman_delta = _nonmanifold(obj) - nonman0

    # First-class mesh-quality metrics (#49): recorded on every commit;
    # enforced as gates once production refinement lands (contract
    # quality.enforced flips the switch — single source of truth).
    stretch = []
    aspects = []
    max_edge = 0.0
    faces_q = _footprint_faces(me, fp)
    for p in faces_q:
        vs = p.vertices
        n = len(vs)
        el = []
        for k in range(n):
            a, b = vs[k], vs[(k + 1) % n]
            length = (me.vertices[a].co - me.vertices[b].co).length
            el.append(length)
            max_edge = max(max_edge, length)
            if a in before and b in before:
                pre = (before[a] - before[b]).length
                if pre > 1e-9:
                    stretch.append(length / pre)
        if p.area > 1e-14:
            longest = max(el)
            aspects.append(longest * longest / (2.0 * p.area))
    aspects_pre = []
    for p in faces_q:
        vs = p.vertices
        if not all(i in before for i in vs):
            continue
        cos = [before[i] for i in vs]
        el = [
            (cos[k] - cos[(k + 1) % len(cos)]).length for k in range(len(cos))
        ]
        area2 = (cos[1] - cos[0]).cross(cos[2] - cos[0]).length
        if area2 > 1e-14:
            aspects_pre.append(max(el) * max(el) / area2)
    aspects.sort()
    aspects_pre.sort()
    # Wall-sampling oracle (#49): the staircase defect is an UNDER-SAMPLED
    # wall — a surviving pre-existing edge left to carry more of the
    # transition than the sampling requirement allows.  The stretch RATIO
    # is set by the authored steepness alone (splitting an edge halves L
    # and Δw alike — the ratio is scale-invariant, √(1+g²) up to 2.46 for
    # a 15/10 profile), so ratio thresholds gate the orthotist's authored
    # profile, not the mesh.  What refinement can and must fix is the
    # post-commit LENGTH of each surviving high-gradient edge against the
    # contract's sampling requirement; sharp pre-creases are exempt exactly
    # as refinement deliberately leaves them (>60° — walls collide there).
    wall_viol = 0
    seen_pairs = set()
    wall_edges = []
    for p in faces_q:
        vs = p.vertices
        n = len(vs)
        for k in range(n):
            a, b = vs[k], vs[(k + 1) % n]
            key = (a, b) if a < b else (b, a)
            if key in seen_pairs or a not in before or b not in before:
                continue
            seen_pairs.add(key)
            pre_len = (before[a] - before[b]).length
            if pre_len > 1e-9:
                wall_edges.append((a, b, pre_len))
    margin = _T["quality"]["wall_sampling_margin"]
    wall_exceed = 0.0
    for a, b, pre_len in wall_edges:
        g = amount_mm * abs(
            weights.get(a, 0.0) - weights.get(b, 0.0)
        ) / (pre_len * 1000.0)
        if g < 0.35:
            continue
        if max(pre_dih.get((a, b), 0.0), pre_dih.get((b, a), 0.0)) > 60.0:
            continue
        rows = max(4, int(math.ceil(2.0 * math.atan(g) / 0.25)))
        h_req = max(
            1.2, (1.5 * amount_mm / g) * math.sqrt(1.0 + g * g) / rows
        )
        # ABSOLUTE bound (#49b): a mean-edge floor here blinded the oracle
        # on coarse scans (decim030 shipped a 21.5 mm wall edge with 0
        # violations) — the sampling requirement must not scale with the
        # scan's own coarseness.
        bound = 1.4 * h_req
        post_mm = (me.vertices[a].co - me.vertices[b].co).length * 1000.0
        wall_exceed = max(wall_exceed, post_mm / bound)
        if post_mm > margin * bound:
            wall_viol += 1
    # Wall-band dihedral spectrum (#49c, recorded for gate derivation): the
    # terracing the orthotist sees lives in the 0.05<w<0.95 band; the
    # full-density reference commit measures p95=39°, coarse commits ~48°.
    band = sorted(
        a for (va, vb), a in post_dih.items()
        if 0.05 < weights.get(va, 0.0) < 0.95
        and 0.05 < weights.get(vb, 0.0) < 0.95
    )
    quality = {
        "stretch_max": max(stretch) if stretch else 0.0,
        "stretch_gt15": sum(1 for s in stretch if s > 1.5),
        "wall_sampling": wall_viol,
        "wall_dih_p95": band[int(len(band) * 0.95)] if band else 0.0,
        "aspect_p95": aspects[int(len(aspects) * 0.95)] if aspects else 0.0,
        "aspect_p95_pre": aspects_pre[int(len(aspects_pre) * 0.95)]
        if aspects_pre else 0.0,
        "aspect_gt8": sum(1 for a in aspects if a > 8.0),
        "max_edge_mm": max_edge * 1000.0,
    }

    _mark(
        f"[{tag}] verts={len(fp)} core_med={core_med:.2f}/{amount_mm} "
        f"outside={outside:.4f} osc_max={osc_max:.3f} osc_mean={osc_mean:.4f} "
        f"rev={rev} decile_rev={decile_rev} new_spikes={new_spikes} "
        f"inverted={inverted} degen={degen} "
        f"selfx={selfx} folds={folds} new_cross={new_cross} holes={holes} "
        f"nonman_delta={nonman_delta} count_ok={count_ok} sign_ok={sign_ok}"
    )
    _mark(
        f"[{tag}] quality: stretch_max={quality['stretch_max']:.2f} "
        f">1.5x:{quality['stretch_gt15']} wall_viol={wall_viol} "
        f"wall_exceed={wall_exceed:.2f} "
        f"wall_dih_p95={quality['wall_dih_p95']:.1f} "
        f"aspect_p95={quality['aspect_p95']:.2f} "
        f">8:{quality['aspect_gt8']} max_edge={quality['max_edge_mm']:.2f}mm"
    )
    return {
        "quality": quality,
        "refined": len(me.vertices) != len(before),
        "d": d, "fp": fp, "holes": holes, "osc_max": osc_max,
        "osc_mean": osc_mean, "rev": rev, "decile_rev": decile_rev,
        "core_med": core_med, "count_ok": count_ok,
        "outside": outside, "new_spikes": new_spikes, "inverted": inverted,
        "degen": degen, "selfx": selfx, "folds": folds,
        "new_cross": new_cross, "nonman_delta": nonman_delta,
        "sign_ok": sign_ok, "weights": weights, "coords": before,
    }


def _gate_vaf(tag, m, amount_mm, feather_mm, h_mm, skip_amount=False,
              skip_osc=False):
    """Validity + Amount + Feather gate block from the contract."""
    v = _T["validity"]
    _gate(
        f"{tag}.validity",
        m["selfx"] <= v["selfx"] and m["inverted"] <= v["inverted"]
        and m["degen"] <= v["degenerate"] and m["holes"] <= v["holes"]
        and m["nonman_delta"] <= v["nonmanifold_delta"]
        and m["folds"] <= _T["fold"]["new_folds"]
        and m["new_cross"] <= _T["wall"]["cross_sheet_new"]
        and m["count_ok"] and m["sign_ok"],
        f"selfx={m['selfx']} inv={m['inverted']} holes={m['holes']} "
        f"folds={m['folds']} new_cross={m['new_cross']} "
        f"count_ok={m['count_ok']}",
    )
    if not skip_osc:
        bound = _osc_gate_mm(amount_mm, feather_mm, h_mm)
        _gate(
            f"{tag}.smooth",
            m["osc_max"] <= bound,
            f"osc_max={m['osc_max']:.2f} bound={bound:.2f}",
        )
    if not skip_amount:
        _gate(
            f"{tag}.amount",
            _T["amount"]["core_lo"] * amount_mm <= m["core_med"]
            <= _T["amount"]["core_hi"] * amount_mm,
            f"core_med={m['core_med']:.2f}",
        )
    _gate(
        f"{tag}.feather",
        m["outside"] <= _T["feather"]["outside_max_mm"] and m["rev"] == 0
        and m["decile_rev"] == 0,
        f"outside={m['outside']:.4f} rev={m['rev']} decile_rev={m['decile_rev']}",
    )
    qc = _T.get("quality", {})
    if qc.get("enforced") and m.get("refined"):
        q = m["quality"]
        # Stretch ratios stay RECORDED (the [tag] quality line) but the
        # enforced sampling gate is wall_sampling: ratio = authored
        # steepness (scale-invariant), length-vs-requirement = the defect.
        _gate(
            f"{tag}.quality",
            q["wall_sampling"] <= qc["wall_sampling_violations"]
            and (q["aspect_p95_pre"] <= 0.0
                 or q["aspect_p95"]
                 <= qc["aspect_p95_factor"] * q["aspect_p95_pre"]),
            f"wall_viol={q['wall_sampling']} stretch={q['stretch_max']:.2f} "
            f"aspect_p95={q['aspect_p95']:.2f}/{q['aspect_p95_pre']:.2f}",
        )


def _match_by_position(m_a, m_b, tol=1e-6):
    """Vertex correspondence by UNDISPLACED position, not by index (#49:
    refined commits renumber vertices; both fixtures share the same base
    scan, so pre-commit coordinates are the durable identity)."""
    keys_b = list(m_b["d"])
    kd = kdtree.KDTree(len(keys_b))
    for n, i in enumerate(keys_b):
        kd.insert(m_b["coords"][i], n)
    kd.balance()
    match = {}
    for i in m_a["d"]:
        _co, n, dist = kd.find(m_a["coords"][i])
        if n is not None and dist < tol:
            match[i] = keys_b[n]
    return match


def _gate_parity(tag, m_direct, m_import, amount_mm, feather_mm, h_mm):
    par = _T["parity"]
    match = _match_by_position(m_direct, m_import)
    keys = list(match.items())
    diffs = [abs(m_direct["d"][a] - m_import["d"][b]) for a, b in keys]
    rms = math.sqrt(sum(x * x for x in diffs) / len(diffs))
    # Two-part max deviation (contract gate 5): the clinically controlled core
    # must match tightly; the transition rim may shift laterally by
    # ~rim_shift_edges edges, which on the profile's peak slope
    # (1.5 * amount/feather) reads as a depth difference without any real
    # shape change.
    core_diffs = [
        abs(m_direct["d"][a] - m_import["d"][b]) for a, b in keys
        if m_direct["weights"].get(a, 0.0) > 0.9
        and m_import["weights"].get(b, 0.0) > 0.9
    ]
    core_maxdd = max(core_diffs) if core_diffs else 0.0
    rim_maxdd = max(diffs) if diffs else 0.0
    rim_bound = par["rim_shift_edges"] * h_mm * 1.5 * amount_mm / feather_mm
    # Effective footprints (w > 0.05) compared through the position match —
    # near-zero mask skirts are not clinical, indices are not identity.
    eff_d = {i for i, w in m_direct["weights"].items()
             if w > 0.05 and i in m_direct["coords"]}
    eff_i = {i for i, w in m_import["weights"].items()
             if w > 0.05 and i in m_import["coords"]}
    both = sum(1 for a, b in keys if a in eff_d and b in eff_i)
    iou = both / max(1, len(eff_d) + len(eff_i) - both)
    _mark(
        f"[{tag}] parity-diag: |eff_d|={len(eff_d)} |eff_i|={len(eff_i)} "
        f"matched={len(keys)} both_eff={both}"
    )
    _gate(
        f"{tag}.parity",
        m_import["osc_max"] <= par["osc_factor"] * m_direct["osc_max"]
        + par["osc_slack_mm"]
        and m_import["new_spikes"] <= m_direct["new_spikes"] + par["spike_slack"]
        and iou >= par["iou_min"] and rms <= par["rms_max_mm"]
        and core_maxdd <= par["core_maxdd_mm"] and rim_maxdd <= rim_bound,
        f"IoU={iou:.3f} rms={rms:.3f} core_maxdd={core_maxdd:.2f} "
        f"rim_maxdd={rim_maxdd:.2f}/{rim_bound:.2f} "
        f"osc={m_import['osc_max']:.2f}vs{m_direct['osc_max']:.2f} "
        f"spikes={m_import['new_spikes']}vs{m_direct['new_spikes']}",
    )


def _gate_cursor_import(tag, obj, style_id, cursor_world):
    """Gate: import at a point on the VISIBLE surface lands there with ~full
    weight and a hole-free field (evaluated-surface correctness, contract 7).

    The vertex under the cursor is resolved on the evaluated surface BEFORE
    the import (the import adds its own preview modifier, which moves it)."""
    settings = bpy.context.scene.rigo_brace
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(depsgraph).to_mesh()
    tree = kdtree.KDTree(len(ev.vertices))
    for v in ev.vertices:
        tree.insert(obj.matrix_world @ v.co, v.index)
    tree.balance()
    _co, under_cursor, dist = tree.find(Vector(cursor_world))
    obj.evaluated_get(depsgraph).to_mesh_clear()

    settings.region_style = style_id
    bpy.context.scene.cursor.location = cursor_world
    try:
        st = bpy.ops.rigo.region_style_import()
    except RuntimeError as exc:
        _gate(tag, False, f"raised {exc}")
        return
    if st != {"FINISHED"}:
        _gate(tag, False, f"returned {st}")
        return
    region = obj.rigo_regions[obj.rigo_region_index]
    weights = _group_weights(obj, region.surface_mask)
    w_at_cursor = weights.get(under_cursor, 0.0)
    adj = _adjacency(obj.data)
    fp = {i for i, w in weights.items() if w > 1e-5}
    holes = 0
    for i in fp:
        if weights.get(i, 0.0) < 0.1 and sum(
            1 for n in adj[i] if weights.get(n, 0.0) > 0.5
        ) >= 3:
            holes += 1
    _gate(
        tag,
        w_at_cursor >= 0.8 and holes == 0 and len(fp) > 50,
        f"w_at_cursor={w_at_cursor:.3f} holes={holes} verts={len(fp)} "
        f"cursor_snap={dist * 1000.0:.1f}mm",
    )


def _commit_valid_or_refuse(tag, obj, amount, feather, weights, nonman0):
    """Hostile-case contract: commit either produces VALID geometry or
    refuses with a bit-exact restore and the live preview kept."""
    mask = obj.rigo_regions[obj.rigo_region_index].surface_mask
    fp = {i for i, w in weights.items() if w > 1e-5}
    pre_dih = _dihedral_map(obj, fp)
    pre_cross = _cross_intersections(obj, fp)
    sig = _topo_sig(obj.data)
    before, before_n, before_fn, pre_polys = _snapshot(obj)
    try:
        st = bpy.ops.rigo.region_apply()
    except RuntimeError as exc:
        st = {"CANCELLED"}
        _mark(f"[{tag}] refused: {exc}")
    if st == {"FINISHED"}:
        weights = _group_weights(obj, mask)
        m = _measure(tag, obj, before, before_n, before_fn, pre_dih,
                     weights, amount, -1.0, nonman0, pre_cross, pre_polys)
        _gate(
            f"{tag}.valid_commit",
            m["selfx"] == 0 and m["inverted"] == 0 and m["degen"] == 0
            and m["holes"] == 0 and m["nonman_delta"] == 0
            and m["outside"] <= 0.001
            and 0.9 * amount <= m["core_med"] <= 1.1 * amount,
            f"selfx={m['selfx']} inv={m['inverted']} core={m['core_med']:.2f}",
        )
    else:
        restored = _refusal_untouched(obj, before, sig)
        preview = obj.modifiers.get(f"RIGO_REGION_PREVIEW_{mask}") is not None
        _gate(f"{tag}.refuse_safe", restored and preview,
              f"untouched_incl_topology={restored} preview_kept={preview}")


def _make_grid(name, size_m, divisions, jitter_frac, seed):
    rng = random.Random(seed)
    bm = bmesh.new()
    bmesh.ops.create_grid(
        bm, x_segments=divisions, y_segments=divisions, size=size_m * 0.5
    )
    bmesh.ops.triangulate(bm, faces=bm.faces)
    spacing = size_m / divisions
    for v in bm.verts:
        if len(v.link_edges) >= 6:
            v.co.x += rng.uniform(-jitter_frac, jitter_frac) * spacing
            v.co.y += rng.uniform(-jitter_frac, jitter_frac) * spacing
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.scene.rigo_brace.scan_object = obj
    bpy.context.view_layer.objects.active = obj
    return obj


def _nearest_vertex(me, point):
    tree = kdtree.KDTree(len(me.vertices))
    for v in me.vertices:
        tree.insert(v.co, v.index)
    tree.balance()
    _co, idx, _d = tree.find(point)
    return idx


def _convex_ridges(obj, weights):
    """Convex signed dihedrals inside the transition band — the literal speed
    bumps in a pressed (concave) wall.  Returns (over 10 deg, over 30 deg).

    Both are reported because they mean different things to the orthotist: a
    10 deg dihedral across one ~4 mm edge is 0.3 mm of height and sits inside
    the surface's own roughness, while a 30 deg one is a bump you can see.
    """
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    small = large = 0
    for e in bm.edges:
        a, b = e.verts[0].index, e.verts[1].index
        wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
        if not (0.05 < wa < 0.95 and 0.05 < wb < 0.95):
            continue
        if len(e.link_faces) != 2:
            continue
        try:
            angle = math.degrees(e.calc_face_angle_signed())
        except ValueError:
            continue
        if angle > 10.0:
            small += 1
        if angle > 30.0:
            large += 1
    bm.free()
    return small, large


def _paint_patch(obj, seed_face, count):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    if seed_face is None:
        # Clean-zone seed identical to the probes' (vertex 9000's first
        # link face) — a different link face grows a patch that grazes the
        # crease and exercises the fallback path instead of refinement.
        bm.verts.ensure_lookup_table()
        seed = bm.verts[9000].link_faces[0]
    else:
        seed = bm.faces[seed_face]
    patch = {seed}
    frontier = [seed]
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


def _run_direct_circle(tag, obj, amount, kind, seed_idx, radius,
                       feather_for_gate=None, commit=True):
    settings = bpy.context.scene.rigo_brace
    me = obj.data
    bpy.context.scene.cursor.location = obj.matrix_world @ me.vertices[seed_idx].co
    settings.region_radius = radius
    settings.region_magnitude = amount
    settings.region_kind = kind
    settings.region_falloff = "SMOOTH"
    bpy.ops.rigo.region_add_circle()
    region = obj.rigo_regions[obj.rigo_region_index]
    weights = _group_weights(obj, region.surface_mask)
    fp = {i for i, w in weights.items() if w > 1e-5}
    pre_dih = _dihedral_map(obj, fp)
    pre_cross = _cross_intersections(obj, fp)
    nonman0 = _nonmanifold(obj)
    before, before_n, before_fn, pre_polys = _snapshot(obj)
    if not commit:
        return None, weights
    bpy.ops.rigo.region_apply()
    # Re-read AFTER commit: once commits refine topology (#49) the vertex
    # group is the only self-consistent weight source for the final mesh.
    weights = _group_weights(obj, region.surface_mask)
    _gate(
        f"{tag}.refined_declared",
        len(me.vertices) - len(before) == region.refined_added,
        f"delta={len(me.vertices) - len(before)} "
        f"declared={region.refined_added}",
    )
    sign = -1.0 if kind == "PRESSURE" else 1.0
    m = _measure(tag, obj, before, before_n, before_fn, pre_dih, weights,
                 amount, sign, nonman0, pre_cross, pre_polys)
    h = _mean_edge_mm(me, fp)
    _gate_vaf(tag, m, amount, feather_for_gate or radius, h)
    return m, weights


def _run_import(tag, obj, style_id, cursor_world, amount, feather_for_gate,
                parity_ref=None, core_required=True):
    settings = bpy.context.scene.rigo_brace
    settings.region_style = style_id
    bpy.context.scene.cursor.location = cursor_world
    t0 = time.perf_counter()
    try:
        st = bpy.ops.rigo.region_style_import()
    except RuntimeError as exc:
        _gate(f"{tag}.import", False, f"raised {exc}")
        return None
    t_import = time.perf_counter() - t0
    if st != {"FINISHED"}:
        _gate(f"{tag}.import", False, f"returned {st}")
        return None
    region = obj.rigo_regions[obj.rigo_region_index]
    weights = _group_weights(obj, region.surface_mask)
    fp = {i for i, w in weights.items() if w > 1e-5}
    pre_dih = _dihedral_map(obj, fp)
    pre_cross = _cross_intersections(obj, fp)
    nonman0 = _nonmanifold(obj)
    before, before_n, before_fn, pre_polys = _snapshot(obj)
    t0 = time.perf_counter()
    st_apply = bpy.ops.rigo.region_apply()
    t_commit = time.perf_counter() - t0
    if st_apply != {"FINISHED"}:
        _gate(f"{tag}.commit", False, f"returned {st_apply}")
        return None
    _gate(
        f"{tag}.refined_declared",
        len(obj.data.vertices) - len(before) == region.refined_added,
        f"delta={len(obj.data.vertices) - len(before)} "
        f"declared={region.refined_added}",
    )
    weights = _group_weights(obj, region.surface_mask)
    sign = -1.0 if region.kind == "PRESSURE" else 1.0
    m = _measure(tag, obj, before, before_n, before_fn, pre_dih, weights,
                 region.magnitude_mm, sign, nonman0, pre_cross, pre_polys)
    h = _mean_edge_mm(obj.data, fp)
    _gate_vaf(tag, m, amount, feather_for_gate, h, skip_amount=not core_required)
    if parity_ref is not None:
        _gate_parity(tag, parity_ref, m, amount, feather_for_gate, h)
    m["op_time"] = t_import + t_commit
    _mark(
        f"[{tag}] import_time={t_import:.3f}s commit_time={t_commit:.3f}s"
    )
    return m


# --------------------------------------------------------------------------- #
def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    settings = bpy.context.scene.rigo_brace
    lib = importlib.import_module(
        "bl_ext.user_default.rigo_brace.core.region_library"
    )
    ro = importlib.import_module(
        "bl_ext.user_default.rigo_brace.operators.region_ops"
    )
    t_all = time.perf_counter()

    def _safe(name, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            _mark(f"[{name}] CASE ERROR={exc!r}\n{traceback.format_exc()}")
            _gate(f"{name}.completed", False, "exception")

    state = {}

    def scan_cases():
        obj = _import_scan(_SCAN)
        m, _w = _run_direct_circle("direct15", obj, 15.0, "PRESSURE", 9000, 30.0)
        state["m_direct15"] = m
        state["cursor"] = tuple(bpy.context.scene.cursor.location)
        st = bpy.ops.rigo.region_style_save(style_name="QA Gate Scan Style")
        _gate("save.v2", st == {"FINISHED"}
              and lib.get_entry(settings.region_style) is not None
              and lib.get_entry(settings.region_style).get("field") is not None,
              "schema v2 with field")
        state["style"] = settings.region_style
        _delete(obj)

        obj = _import_scan(_SCAN)
        _run_direct_circle("direct5", obj, 5.0, "PRESSURE", 9000, 30.0)
        bpy.ops.rigo.region_style_save(style_name="QA Gate Scan Style5")
        state["style5"] = settings.region_style
        _delete(obj)
        obj = _import_scan(_SCAN)
        _run_direct_circle("expand15", obj, 15.0, "EXPANSION", 9000, 30.0)
        _delete(obj)

        # painted path (geodesic feather regression): a clean-area patch is
        # the gated product case; the wrinkled face-5000 armpit patch is the
        # hostile stress case (commit must repair or warn, never tear).
        # paint15: 240 faces off v9000 — its wall crosses mild wrinkles that
        # cost one refinement-seam sliver, which the commit's dissolution
        # retry must absorb: the case is gated REFINED, no fallback.  A
        # genuinely crease-bound patch may still take the warned unrefined
        # FALLBACK (paint15_hostile), never a tear.
        for tag, seed_face, count, gated in (
            ("paint15", None, 240, True),
            ("paint15_hostile", 5000, 300, False),
        ):
            obj = _import_scan(_SCAN)
            _paint_patch(obj, seed_face, count)
            settings.region_kind = "PRESSURE"
            settings.region_magnitude = 15.0
            settings.region_feather = 10.0
            settings.region_falloff = "SMOOTH"
            bpy.ops.rigo.region_add()
            region = obj.rigo_regions[obj.rigo_region_index]
            weights = _group_weights(obj, region.surface_mask)
            nonman0 = _nonmanifold(obj)
            if gated:
                fp = {i for i, w in weights.items() if w > 1e-5}
                pre_dih = _dihedral_map(obj, fp)
                pre_cross = _cross_intersections(obj, fp)
                before, before_n, before_fn, pre_polys = _snapshot(obj)
                bpy.ops.rigo.region_apply()
                # #49 acceptance: a steep painted wall on the wrinkled scan
                # must commit REFINED (seam-sliver dissolution) — a warned
                # fallback here is a regression, not an allowed outcome.
                _gate(
                    f"{tag}.refined_commit",
                    region.refined_added > 0,
                    f"refined_added={region.refined_added}",
                )
                _gate(
                    f"{tag}.refined_declared",
                    len(obj.data.vertices) - len(before)
                    == region.refined_added,
                    f"delta={len(obj.data.vertices) - len(before)} "
                    f"declared={region.refined_added}",
                )
                weights = _group_weights(obj, region.surface_mask)
                m = _measure(tag, obj, before, before_n, before_fn, pre_dih,
                             weights, 15.0, -1.0, nonman0, pre_cross, pre_polys)
                _gate_vaf(tag, m, 15.0, 10.0, _mean_edge_mm(obj.data, fp))
            else:
                _commit_valid_or_refuse(tag, obj, 15.0, 10.0, weights, nonman0)
            _delete(obj)

    def import_cases():
        style = state["style"]
        cursor = state["cursor"]
        obj = _import_scan(_SCAN)
        m = _run_import("import_same", obj, style, cursor, 15.0, 30.0,
                        parity_ref=state["m_direct15"])
        _delete(obj)

        # Candidate A (legacy v1 = IDW path): same entry without the field.
        entry = dict(lib.get_entry(style))
        entry = {k: v for k, v in entry.items() if k != "field"}
        entry["id"] = "QA_GATE_V1"
        entry["label"] = "QA Gate Scan Style"  # cleaned up by label
        entry["schema_version"] = 1
        lib.upsert_entry(entry)
        obj = _import_scan(_SCAN)
        m = _run_import("import_v1idw", obj, "QA_GATE_V1", cursor, 15.0, 30.0,
                        parity_ref=state["m_direct15"])
        _delete(obj)
        lib.delete_entry("QA_GATE_V1")

        obj = _import_scan(_SCAN)
        moved = obj.matrix_world @ obj.data.vertices[20000].co
        _delete(obj)
        obj = _import_scan(_SCAN)
        _run_import("import_moved", obj, style, tuple(moved), 15.0, 30.0)
        _delete(obj)

        # decim015 (#49b): the coarse-patient-scan class from the orthotist's
        # screenshots — a mean-edge floor in the refinement criterion used to
        # leave these walls at scan density (21.5 mm edges on decim030, zero
        # violations flagged by the equally-floored oracle).  Refinement must
        # ENGAGE here and the floorless wall-sampling gate must hold.
        for tag, ratio, must_refine in (
            ("import_decim065", 0.65, False), ("import_decim030", 0.30, False),
            ("import_decim015", 0.15, True),
        ):
            obj = _import_scan(_SCAN)
            mod = obj.modifiers.new("QA_DEC", "DECIMATE")
            mod.ratio = ratio
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=mod.name)
            _run_import(tag, obj, style, cursor, 15.0, 30.0)
            if must_refine:
                region = obj.rigo_regions[obj.rigo_region_index]
                _gate(
                    f"{tag}.refined_commit",
                    region.refined_added > 0,
                    f"refined_added={region.refined_added}",
                )
            _delete(obj)

        # repeated import onto already-committed geometry (screenshot case).
        # 5+5 mm is a feasible clinical stack — fully gated; 15+15 mm exceeds
        # what the sample torso can absorb (30 mm total on a ~60 mm body
        # radius), so it is a warn-path stress case: valid state, no leakage,
        # and strictly better than the pre-fix wreckage.
        def _repeat(tag, style_id, amount, gated):
            obj = _import_scan(_SCAN)
            _run_import(f"{tag}_a", obj, style_id, cursor, amount, 30.0)
            settings.region_style = style_id
            bpy.context.scene.cursor.location = cursor
            st = bpy.ops.rigo.region_style_import()
            if st != {"FINISHED"}:
                _gate(f"{tag}_b.import", False, f"returned {st}")
                _delete(obj)
                return
            region = obj.rigo_regions[obj.rigo_region_index]
            weights = _group_weights(obj, region.surface_mask)
            nonman0 = _nonmanifold(obj)
            if gated:
                fp = {i for i, w in weights.items() if w > 1e-5}
                pre_dih = _dihedral_map(obj, fp)
                pre_cross = _cross_intersections(obj, fp)
                before, before_n, before_fn, pre_polys = _snapshot(obj)
                bpy.ops.rigo.region_apply()
                weights = _group_weights(obj, region.surface_mask)
                m = _measure(f"{tag}_b", obj, before, before_n, before_fn,
                             pre_dih, weights, amount, -1.0, nonman0,
                             pre_cross, pre_polys)
                _gate(
                    f"{tag}_b.validity",
                    m["selfx"] == 0 and m["inverted"] == 0 and m["degen"] == 0
                    and m["holes"] == 0 and m["nonman_delta"] == 0,
                    f"selfx={m['selfx']} inv={m['inverted']} holes={m['holes']}",
                )
                _gate(f"{tag}_b.feather", m["outside"] <= 0.001,
                      f"outside={m['outside']:.4f}")
            else:
                _commit_valid_or_refuse(f"{tag}_b", obj, amount, 30.0,
                                        weights, nonman0)
            _delete(obj)

        _repeat("repeat5", state["style5"], 5.0, gated=True)
        _repeat("repeat15", style, 15.0, gated=False)

        # import while another region's preview is live (RC2 frame test):
        # the cursor sits on the VISIBLE (previewed) surface; the evaluated
        # vertex under the cursor must receive ~full weight.
        obj = _import_scan(_SCAN)
        me = obj.data
        bpy.context.scene.cursor.location = obj.matrix_world @ me.vertices[9000].co
        settings.region_radius = 30.0
        settings.region_magnitude = 15.0
        settings.region_kind = "PRESSURE"
        bpy.ops.rigo.region_add_circle()  # live preview, NOT committed
        depsgraph = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(depsgraph).to_mesh()
        visible = obj.matrix_world @ ev.vertices[9000].co.copy()
        obj.evaluated_get(depsgraph).to_mesh_clear()
        _gate_cursor_import("preview_stack", obj, style, visible)
        _delete(obj)

        # evaluated-surface consistency: live 20 mm displace on the target
        obj = _import_scan(_SCAN)
        v = obj.data.vertices[9000]
        mod = obj.modifiers.new("QA_INFLATE", "DISPLACE")
        mod.direction = "NORMAL"
        mod.mid_level = 0.0
        mod.strength = 0.020
        depsgraph = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(depsgraph).to_mesh()
        visible = obj.matrix_world @ ev.vertices[9000].co.copy()
        obj.evaluated_get(depsgraph).to_mesh_clear()
        _gate_cursor_import("eval_consistency", obj, style, visible)
        _delete(obj)

        # contract 7/8: a live topology-changing modifier must make the import
        # REFUSE with an actionable error and mutate NOTHING.
        obj = _import_scan(_SCAN)
        mod = obj.modifiers.new("QA_SUBD", "SUBSURF")
        mod.levels = 1
        settings.region_style = style
        bpy.context.scene.cursor.location = cursor
        before_pos = {v.index: v.co.copy() for v in obj.data.vertices}
        n_regions = len(obj.rigo_regions)
        n_groups = len(obj.vertex_groups)
        msg = ""
        try:
            st = bpy.ops.rigo.region_style_import()
        except RuntimeError as exc:
            st = {"CANCELLED"}
            msg = str(exc)
        unchanged = (
            len(obj.rigo_regions) == n_regions
            and len(obj.vertex_groups) == n_groups
            and all(
                (obj.data.vertices[i].co - before_pos[i]).length == 0.0
                for i in before_pos
            )
        )
        _gate(
            "import_refusal",
            st != {"FINISHED"} and unchanged
            and ("vertex count" in msg or "modifier" in msg),
            f"status={st} unchanged={unchanged} msg={msg[:80]}",
        )
        _delete(obj)

        # determinism: identical inputs -> bit-equal weights
        runs = []
        for _ in range(2):
            obj = _import_scan(_SCAN)
            settings.region_style = style
            bpy.context.scene.cursor.location = state["cursor"]
            bpy.ops.rigo.region_style_import()
            region = obj.rigo_regions[obj.rigo_region_index]
            runs.append(_group_weights(obj, region.surface_mask))
            _delete(obj)
        _gate("determinism", runs[0] == runs[1],
              f"n0={len(runs[0])} n1={len(runs[1])}")

    def patient_cases():
        obj = _import_scan(_PATIENT)
        me = obj.data
        xs = [v.co.x for v in me.vertices]
        ys = [v.co.y for v in me.vertices]
        zs = [v.co.z for v in me.vertices]
        cx, cz = (min(xs) + max(xs)) * 0.5, (min(zs) + max(zs)) * 0.5
        back = _nearest_vertex(me, Vector((cx, min(ys), cz)))
        front = _nearest_vertex(me, Vector((cx, max(ys), cz)))
        m_back, _w = _run_direct_circle(
            "patient_back", obj, 15.0, "PRESSURE", back, 30.0
        )
        t0 = time.perf_counter()
        st = bpy.ops.rigo.region_style_save(style_name="QA Gate Patient Style")
        state["style_patient"] = settings.region_style
        _delete(obj)

        obj = _import_scan(_PATIENT)
        m_front, _w = _run_direct_circle(
            "patient_front", obj, 15.0, "PRESSURE", front, 30.0
        )
        front_cursor = tuple(bpy.context.scene.cursor.location)
        _delete(obj)

        obj = _import_scan(_PATIENT)
        m = _run_import("patient_import_front", obj, state["style_patient"],
                        front_cursor, 15.0, 30.0, parity_ref=m_front)
        # Contract 9 times the PRODUCT operators (import + commit), not the
        # test harness's own bmesh/BVH measurement passes around them.
        op_time = m["op_time"] if m else 99.0
        _gate("perf", op_time <= _T["perf"]["import_commit_max_s"],
              f"import+commit ops={op_time:.2f}s on patient scan")
        _delete(obj)

        # cross-scan import (style authored on Brace Sample)
        obj = _import_scan(_PATIENT)
        back_cursor = obj.matrix_world @ obj.data.vertices[back].co
        _run_import("patient_import_cross", obj, state["style"],
                    tuple(back_cursor), 15.0, 30.0)
        _delete(obj)

    def flat_cases():
        g = _make_grid("QA_GATE_SRC", 0.3, 100, 0.3, 1)
        seed = _nearest_vertex(g.data, Vector((0, 0, 0)))
        m_flat, _w = _run_direct_circle(
            "flat_direct", g, 15.0, "PRESSURE", seed, 30.0
        )
        bpy.ops.rigo.region_style_save(style_name="QA Gate Flat Style")
        style_flat = settings.region_style
        _delete(g)
        for tag, divs, jseed in (
            ("flat_dense", 150, 2), ("flat_same", 100, 3), ("flat_coarse", 50, 4)
        ):
            g = _make_grid(f"QA_GATE_{tag}", 0.3, divs, 0.3, jseed)
            _run_import(tag, g, style_flat, (0.0, 0.0, 0.0), 15.0, 30.0)
            _delete(g)

    def oppwall_cases(ro):
        # Wave 1 P0 red fixture (from hardendbg): a 24 mm-thick body.
        # 30 mm must REFUSE with the scan untouched; 10 mm (10+3 < 24) must
        # commit cleanly — proving the guard does not over-refuse.
        settings2 = bpy.context.scene.rigo_brace

        def build(name):
            bm = bmesh.new()
            bmesh.ops.create_uvsphere(
                bm, u_segments=96, v_segments=64, radius=1.0
            )
            for vtx in bm.verts:
                vtx.co.x *= 0.09
                vtx.co.y *= 0.012
                vtx.co.z *= 0.09
            bmesh.ops.triangulate(bm, faces=bm.faces)
            mesh = bpy.data.meshes.new(name)
            bm.to_mesh(mesh)
            bm.free()
            body = bpy.data.objects.new(name, mesh)
            bpy.context.scene.collection.objects.link(body)
            settings2.scan_object = body
            bpy.context.view_layer.objects.active = body
            body.select_set(True)
            return body

        for tag, amount, expect_commit in (
            ("oppwall_attack", 30.0, False),
            ("oppwall_feasible", 10.0, True),
        ):
            obj = build(f"QA_{tag}")
            me = obj.data
            top = max(me.vertices, key=lambda vtx: vtx.co.y)
            bpy.context.scene.cursor.location = obj.matrix_world @ top.co
            settings2.region_radius = 25.0
            settings2.region_magnitude = amount
            settings2.region_kind = "PRESSURE"
            settings2.region_falloff = "SMOOTH"
            bpy.ops.rigo.region_add_circle()
            region = obj.rigo_regions[obj.rigo_region_index]
            weights = _group_weights(obj, region.surface_mask)
            fp = {i for i, w in weights.items() if w > 1e-5}
            pre_dih = _dihedral_map(obj, fp)
            pre_cross = _cross_intersections(obj, fp)
            nonman0 = _nonmanifold(obj)
            sig = _topo_sig(me)
            before, before_n, before_fn, pre_polys = _snapshot(obj)
            msg = ""
            try:
                st = bpy.ops.rigo.region_apply()
            except RuntimeError as exc:
                st = {"CANCELLED"}
                msg = str(exc)
            if expect_commit:
                ok_commit = st == {"FINISHED"}
                if ok_commit:
                    weights = _group_weights(obj, region.surface_mask)
                    m = _measure(tag, obj, before, before_n, before_fn,
                                 pre_dih, weights, amount, -1.0, nonman0,
                                 pre_cross)
                    _gate_vaf(tag, m, amount, 25.0,
                              _mean_edge_mm(me, fp))
                else:
                    _gate(tag, False, f"over-refused: {msg[:90]}")
            else:
                restored = _refusal_untouched(obj, before, sig)
                preview = obj.modifiers.get(
                    f"RIGO_REGION_PREVIEW_{region.surface_mask}"
                ) is not None
                _gate(
                    tag,
                    st != {"FINISHED"} and restored and preview
                    and "opposite" in msg,
                    f"status={st} restored={restored} preview={preview} "
                    f"msg={msg[:90]}",
                )
            _delete(obj)

    def flip_confirm_unit_case(ro):
        # #49e narrowed the single-triangle rotation test: a face whose own
        # normal passed 90 deg only BLOCKS a commit when the surface confirms
        # it by creasing a shared edge past 90 deg.  That predicate is now the
        # sole ship-blocking answer for an isolated inversion and nothing
        # exercised it.  Two arms on the same two-triangle fixture: a face
        # rotated past 90 deg whose neighbour still agrees (a steep wall
        # tilting - NOT a defect, this is what threw healthy refined commits
        # away for the staircase), and one that folds back onto its neighbour.
        def build(apex):
            mesh = bpy.data.meshes.new("QA_FLIPU")
            mesh.from_pydata(
                [(0.0, 0.0, 0.0), (0.01, 0.0, 0.0), (0.005, 0.010, 0.0),
                 apex],
                [], [(0, 1, 2), (1, 0, 3)],
            )
            mesh.update()
            return mesh

        # Arm 1: neighbour dihedral healthy (faces nearly coplanar).
        benign = build((0.005, -0.010, 0.0005))
        benign_dot = benign.polygons[0].normal.dot(benign.polygons[1].normal)
        kept_benign = ro._surface_confirmed_flips(benign, {1}, [(0, 1)])
        # Arm 2: the second face folded back over the first.
        folded = build((0.005, 0.008, 0.0005))
        folded_dot = folded.polygons[0].normal.dot(folded.polygons[1].normal)
        kept_folded = ro._surface_confirmed_flips(folded, {1}, [(0, 1)])
        # Arm 3: a flipped face with NO neighbourhood to consult must keep
        # the strict answer rather than be silently forgiven.
        kept_alone = ro._surface_confirmed_flips(benign, {1}, [])
        _gate(
            "flip_confirm_unit",
            not kept_benign and kept_folded == {1} and kept_alone == {1},
            f"neighbour dot {benign_dot:.2f} -> not confirmed "
            f"({sorted(kept_benign)}); dot {folded_dot:.2f} -> confirmed "
            f"({sorted(kept_folded)}); no neighbours -> strict "
            f"({sorted(kept_alone)})",
        )
        bpy.data.meshes.remove(benign)
        bpy.data.meshes.remove(folded)

    def fold_unit_case(ro):
        # Wave 1 P0: the pre-creased <90°-rotation fold (hardendbg
        # adjfold.foldover_creased).  The production predicate must flag it,
        # the independent dihedral-degree oracle must agree, and both must
        # stay silent on a benign displacement of the same crease.
        def build(d_post):
            mesh = bpy.data.meshes.new("QA_FOLDU")
            mesh.from_pydata(
                [(0.0, 0.0, 0.0), (0.01, 0.0, 0.0), (0.005, 0.010, 0.0),
                 (0.005, 0.00087, 0.00996)],
                [], [(0, 1, 2), (1, 0, 3)],
            )
            mesh.update()
            body = bpy.data.objects.new("QA_FOLDU", mesh)
            bpy.context.scene.collection.objects.link(body)
            pre_normals = {p.index: p.normal.copy() for p in mesh.polygons}
            pre_ang = _dihedral_map(body, {0, 1, 2, 3})
            mesh.vertices[3].co = Vector(d_post)
            mesh.update()
            post_ang = _dihedral_map(body, {0, 1, 2, 3})
            detected = ro._folded_pairs(mesh, [(0, 1)], pre_normals)
            _delete(body)
            return detected, max(pre_ang.values()), max(post_ang.values())

        folded, pre_a, post_a = build((0.005, 0.00995, 0.00087))
        benign, _pre_b, post_b = build((0.005, -0.001, 0.0105))
        oracle_flags = (
            post_a > _T["fold"]["oracle_post_deg"]
            and pre_a < _T["fold"]["oracle_pre_deg"]
        )
        oracle_clean = post_b <= _T["fold"]["oracle_post_deg"]
        _gate(
            "fold_predicate_unit",
            folded == {0, 1} and oracle_flags
            and not benign and oracle_clean,
            f"folded={sorted(folded)} pre={pre_a:.0f}deg post={post_a:.0f}deg "
            f"benign={sorted(benign)} benign_post={post_b:.0f}deg",
        )
        _gate(
            "contract_constants",
            abs(ro._WALL_CLEARANCE_MM - _T["wall"]["clearance_mm"]) < 1e-9
            and abs(ro._FOLD_DOT - _T["fold"]["dot"]) < 1e-9
            and abs(ro._FOLD_PRE_DOT - _T["fold"]["pre_dot"]) < 1e-9
            and abs(
                ro._FLIP_CONFIRM_DOT - _T["fold"]["flip_confirm_dot"]
            ) < 1e-9
            # #49e's three tuning constants were reachable by nothing: the
            # rim mollification width, the geodesic gate that is the SOLE
            # safety argument for measuring Euclidean distance on a folded
            # torso, and the legacy-region reconstruction tolerance.
            and ro._RIM_SMOOTH_PASSES == _T["rim"]["smooth_passes"]
            and ro._RIM_GATE_STEPS == _T["rim"]["gate_steps"]
            and abs(
                ro._RIM_FIELD_TOLERANCE - _T["rim"]["field_tolerance"]
            ) < 1e-12
            # #49k: the tolerance that decides whether a PLACED STYLE's stored
            # field is trusted for refinement.  Too loose accepts a wrong
            # chart frame; too tight silently drops the whole library route
            # back to the pre-#49k interpolation.
            and abs(
                ro._STYLE_FIELD_TOLERANCE - _T["style"]["field_tolerance"]
            ) < 1e-12,
            f"prod=({ro._WALL_CLEARANCE_MM},{ro._FOLD_DOT},"
            f"{ro._FOLD_PRE_DOT},{ro._FLIP_CONFIRM_DOT}) rim=("
            f"{ro._RIM_SMOOTH_PASSES},{ro._RIM_GATE_STEPS},"
            f"{ro._RIM_FIELD_TOLERANCE}) style={ro._STYLE_FIELD_TOLERANCE}",
        )

    def wave2_mirror_case():
        # Wave 2: mirror derives from the undisplaced snapshot via the
        # field path (no Voronoi collapse, no displaced-geometry sampling),
        # maps sided labels, and pairing metadata survives into styles.
        import json as _json

        obj = _import_scan(_SCAN)
        me = obj.data
        bpy.context.scene.cursor.location = obj.matrix_world @ me.vertices[9000].co
        settings.region_radius = 30.0
        settings.region_magnitude = 8.0
        settings.region_kind = "PRESSURE"
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add_circle()
        src = obj.rigo_regions[obj.rigo_region_index]
        src.anatomical_label = "AXILLA_L"
        n_src = len(_group_weights(obj, src.surface_mask))
        bpy.ops.rigo.region_apply()
        bpy.ops.rigo.region_mirror()
        mir = obj.rigo_regions[obj.rigo_region_index]
        w_m = _group_weights(obj, mir.surface_mask)
        snap_present = obj.get("rigo_style_src_" + mir.surface_mask) is not None
        adj = _adjacency(me)
        holes = sum(
            1 for i in set(w_m) | {n for i in w_m for n in adj[i]}
            if w_m.get(i, 0.0) < 0.1
            and sum(1 for n in adj[i] if w_m.get(n, 0.0) > 0.5) >= 3
        )
        _gate(
            "mirror.field_transfer",
            snap_present and holes == 0
            and 0.5 * n_src <= len(w_m) <= 1.8 * n_src,
            f"src={n_src} mir={len(w_m)} holes={holes} snapshot={snap_present}",
        )
        _gate(
            "mirror.provenance",
            mir.kind == "EXPANSION" and mir.anatomical_label == "AXILLA_R"
            and mir.label_auto_mapped and mir.mirrored_from == src.name
            and mir.opposing_region == 0
            and obj.rigo_regions[0].opposing_region == obj.rigo_region_index,
            f"kind={mir.kind} label={mir.anatomical_label} "
            f"auto={mir.label_auto_mapped} from={mir.mirrored_from!r}",
        )
        fp = {i for i, w in w_m.items() if w > 1e-5}
        pre_dih = _dihedral_map(obj, fp)
        pre_cross = _cross_intersections(obj, fp)
        nonman0 = _nonmanifold(obj)
        before, before_n, before_fn, pre_polys = _snapshot(obj)
        st = bpy.ops.rigo.region_apply()
        if st == {"FINISHED"}:
            w_m = _group_weights(obj, mir.surface_mask)
            m = _measure("mirror_commit", obj, before, before_n, before_fn,
                         pre_dih, w_m, 8.0, 1.0, nonman0, pre_cross, pre_polys)
            _gate(
                "mirror.commit_validity",
                m["selfx"] == 0 and m["inverted"] == 0 and m["degen"] == 0
                and m["folds"] == 0 and m["new_cross"] == 0
                and m["holes"] == 0 and m["count_ok"]
                and 0.9 * 8.0 <= m["core_med"] <= 1.1 * 8.0,
                f"core={m['core_med']:.2f}",
            )
        else:
            _gate("mirror.commit_validity", False, f"commit returned {st}")
        st = bpy.ops.rigo.region_style_save(style_name="QA W2 Mirror Style")
        e_m = lib.get_entry(settings.region_style)
        cm = (e_m or {}).get("clinical") or {}
        _gate(
            "mirror.style_save",
            st == {"FINISHED"} and e_m.get("field") is not None
            and cm.get("mirrored_from") == src.name
            and cm.get("paired") is True
            and cm.get("counterpart_kind") == "PRESSURE"
            and cm.get("label_auto_mapped") is True,
            f"clinical={sorted(cm)}",
        )
        obj.rigo_region_index = 0
        bpy.ops.rigo.region_style_save(style_name="QA W2 Source Style")
        e_s = lib.get_entry(settings.region_style)
        cs = (e_s or {}).get("clinical") or {}
        offset_x = abs((cs.get("counterpart_center_offset_mm") or [0, 0, 0])[0])
        _gate(
            "pairing.metadata",
            cs.get("paired") is True and cs.get("counterpart_kind") == "EXPANSION"
            and cs.get("anatomical_label") == "AXILLA_L"
            and offset_x > 10.0
            and (e_s.get("max_geodesic_mm") or 0.0) > 15.0,
            f"offset_x={offset_x:.1f}mm geo={e_s.get('max_geodesic_mm')}",
        )
        # Midline labels are never auto-mapped.
        obj.rigo_regions[0].anatomical_label = "WAISTLINE"
        obj.rigo_region_index = 0
        bpy.ops.rigo.region_mirror()
        mid = obj.rigo_regions[obj.rigo_region_index]
        _gate(
            "mirror.midline_label",
            mid.anatomical_label == "WAISTLINE" and not mid.label_auto_mapped,
            f"label={mid.anatomical_label} auto={mid.label_auto_mapped}",
        )
        _delete(obj)

    def wave2_horseshoe_case():
        # Wave 2: on-pad anchor + intrinsic trim keep a C-shaped pad whole
        # through save -> import (was IoU 0.123 / 78% lost).
        import json as _json

        def c_pad(name):
            g = _make_grid(name, 0.3, 100, 0.0, 11)
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_mode(type="FACE")
            bpy.ops.mesh.select_all(action="DESELECT")
            bm = bmesh.from_edit_mesh(g.data)
            for f in bm.faces:
                c = f.calc_center_median()
                r = math.hypot(c.x, c.y) * 1000.0
                ang = abs(math.degrees(math.atan2(c.y, c.x)))
                f.select = 45.0 <= r <= 75.0 and ang > 40.0
            bmesh.update_edit_mesh(g.data)
            return g

        g = c_pad("QA_W2_HS")
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 5.0
        settings.region_feather = 10.0
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add()
        region = g.rigo_regions[g.rigo_region_index]
        w_auth = _group_weights(g, region.surface_mask)
        auth_eff = {i for i, w in w_auth.items() if w > 0.05}
        snap = _json.loads(g["rigo_style_src_" + region.surface_mask])
        anchor = Vector(snap["anchor_world"])
        r_anchor = math.hypot(anchor.x, anchor.y) * 1000.0
        _gate(
            "horseshoe.anchor_on_pad",
            40.0 <= r_anchor <= 80.0,
            f"anchor_r={r_anchor:.1f}mm (pad spans 45-75mm; centroid would "
            f"sit near 18mm, in the gap)",
        )
        bpy.ops.rigo.region_apply()
        bpy.ops.rigo.region_style_save(style_name="QA W2 HS Style")
        hs_id = settings.region_style
        auth_geo = lib.get_entry(hs_id).get("max_geodesic_mm") or 0.0
        _gate(
            "horseshoe.intrinsic_size",
            auth_geo > 100.0,
            f"max_geodesic={auth_geo:.0f}mm (chart chord extent is only ~75)",
        )
        _delete(g)
        g = _make_grid("QA_W2_HS2", 0.3, 100, 0.0, 11)
        settings.region_style = hs_id
        bpy.context.scene.cursor.location = anchor
        st = bpy.ops.rigo.region_style_import()
        region = g.rigo_regions[g.rigo_region_index]
        w_imp = _group_weights(g, region.surface_mask)
        imp_eff = {i for i, w in w_imp.items() if w > 0.05}
        iou = len(auth_eff & imp_eff) / max(1, len(auth_eff | imp_eff))
        _gate(
            "horseshoe.import_iou",
            st == {"FINISHED"} and iou >= _T["parity"]["iou_min"],
            f"IoU={iou:.3f} authored={len(auth_eff)} imported={len(imp_eff)}",
        )
        _delete(g)

    def wave2_size_case():
        # Wave 2: surface-mm size semantics — a flat-authored footprint
        # keeps its along-the-surface size on curved bodies (independent
        # test-side geodesic measurement, not the production trim numbers).
        g = _make_grid("QA_W2_SZ", 0.3, 100, 0.0, 12)
        seed = _nearest_vertex(g.data, Vector((0, 0, 0)))
        bpy.context.scene.cursor.location = g.matrix_world @ g.data.vertices[seed].co
        settings.region_radius = 60.0
        settings.region_magnitude = 5.0
        settings.region_kind = "PRESSURE"
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add_circle()
        bpy.ops.rigo.region_apply()
        bpy.ops.rigo.region_style_save(style_name="QA W2 Size Style")
        sz_id = settings.region_style
        authored = lib.get_entry(sz_id).get("max_geodesic_mm") or 0.0
        _gate(
            "size.authored_geodesic",
            35.0 <= authored <= 60.0,
            f"authored={authored:.1f}mm (60mm circle; effective w>0.05 "
            f"footprint ends inside the feather tail)",
        )
        _delete(g)

        def cylinder(name, radius):
            n_theta = max(48, int(2.0 * math.pi * radius / 0.003))
            n_z = 120
            dz = 0.003
            verts, faces = [], []
            for k in range(n_z):
                z = (k - n_z * 0.5) * dz
                for t in range(n_theta):
                    a = 2.0 * math.pi * t / n_theta
                    verts.append(
                        (radius * math.cos(a), radius * math.sin(a), z)
                    )
            for k in range(n_z - 1):
                for t in range(n_theta):
                    a0 = k * n_theta + t
                    a1 = k * n_theta + (t + 1) % n_theta
                    faces.append((a0, a1, a1 + n_theta))
                    faces.append((a0, a1 + n_theta, a0 + n_theta))
            mesh = bpy.data.meshes.new(name)
            mesh.from_pydata(verts, [], faces)
            mesh.update()
            body = bpy.data.objects.new(name, mesh)
            bpy.context.scene.collection.objects.link(body)
            settings.scan_object = body
            bpy.context.view_layer.objects.active = body
            body.select_set(True)
            return body

        for tag, radius in (("size.r60", 0.06), ("size.r95", 0.095)):
            cyl = cylinder(f"QA_{tag}", radius)
            settings.region_style = sz_id
            bpy.context.scene.cursor.location = Vector((radius, 0.0, 0.0))
            try:
                st = bpy.ops.rigo.region_style_import()
            except RuntimeError as exc:
                _gate(tag, False, f"raised {exc}")
                _delete(cyl)
                continue
            region = cyl.rigo_regions[cyl.rigo_region_index]
            w = _group_weights(cyl, region.surface_mask)
            eff = {i for i, wt in w.items() if wt > 0.05}
            me2 = cyl.data
            seed2 = min(
                eff,
                key=lambda i: (me2.vertices[i].co - Vector((radius, 0, 0))).length_squared,
            )
            neighbors = {}
            for e in me2.edges:
                a, b = e.vertices
                if a in eff and b in eff:
                    length = (me2.vertices[a].co - me2.vertices[b].co).length
                    neighbors.setdefault(a, []).append((b, length))
                    neighbors.setdefault(b, []).append((a, length))
            import heapq as _heapq
            dist = {seed2: 0.0}
            heap = [(0.0, seed2)]
            while heap:
                d, i = _heapq.heappop(heap)
                if d > dist.get(i, 1e30):
                    continue
                for j, length in neighbors.get(i, ()):
                    nd = d + length
                    if nd < dist.get(j, 1e30):
                        dist[j] = nd
                        _heapq.heappush(heap, (nd, j))
            realized = max(dist.values()) * 1000.0 if dist else 0.0
            frac = abs(realized - authored) / authored if authored else 1.0
            _gate(
                tag,
                st == {"FINISHED"}
                and frac <= _T["size"]["surface_tolerance_frac"],
                f"realized={realized:.1f}mm authored={authored:.1f}mm "
                f"({frac * 100.0:.1f}% off along the surface)",
            )
            _delete(cyl)

    def w49_cases():
        # The user workflow that exposed #49: paint -> commit -> Smooth ->
        # inspect.  Plus refinement determinism, overlap-mask preservation
        # (audit B3) and the already-dense no-op guarantee.
        def painted_commit():
            obj = _import_scan(_SCAN)
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_mode(type="FACE")
            bpy.ops.mesh.select_all(action="DESELECT")
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            frontier = [bm.verts[9000].link_faces[0]]
            patch = set(frontier)
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
            settings.region_kind = "PRESSURE"
            settings.region_magnitude = 15.0
            settings.region_feather = 10.0
            settings.region_falloff = "SMOOTH"
            bpy.ops.rigo.region_add()
            region = obj.rigo_regions[obj.rigo_region_index]
            pre_dih = _dihedral_map(
                obj, set(_group_weights(obj, region.surface_mask))
            )
            bpy.ops.object.mode_set(mode="OBJECT")
            # Pre-commit state the #49e/#49h gates need: the undisplaced
            # surface (to measure realized correction depth against), the
            # vertex count (to tell refinement-born vertices apart) and the
            # authored field itself.
            me = obj.data
            pre = {
                "coords": [v.co.copy() for v in me.vertices],
                "polys": [tuple(p.vertices) for p in me.polygons],
                "n_orig": len(me.vertices),
                "group": obj.vertex_groups.get(region.surface_mask).index,
                "offset": -region.magnitude_mm * 0.001,
                "feather_mm": 10.0,
                "mesh": me.copy(),
            }
            pre["rim_field"] = ro._authored_rim_field(
                me, pre["group"], region.falloff_type
            )
            bpy.ops.rigo.region_apply()
            return obj, region, pre_dih, pre

        def _percentile(values, fraction=0.95):
            if not values:
                return 0.0
            values = sorted(values)
            return values[min(len(values) - 1, int(len(values) * fraction))]

        def _candidate_fields(obj, region, pre):
            """Rebuild BOTH candidate falloff fields test-side from the mesh:
            the #49e distance-to-the-mollified-rim-CURVE field, and the
            pre-#49e edge-walk Dijkstra distance from the rim VERTICES.

            Without the second arm a gate is satisfied by either metric — and
            measured: with the field reverted to Dijkstra the entire battery
            stayed green (failed_gates=[]).
            """
            me = pre["mesh"]
            weights = _group_weights(obj, region.surface_mask)
            weights = {i: w for i, w in weights.items() if i < len(me.vertices)}
            coords = {i: me.vertices[i].co.copy() for i in weights}
            adjacency = {i: [] for i in weights}
            rim = set()
            for edge in me.edges:
                a, b = edge.vertices
                a_in, b_in = a in adjacency, b in adjacency
                if a_in and b_in:
                    adjacency[a].append(b)
                    adjacency[b].append(a)
                elif a_in:
                    rim.add(a)
                elif b_in:
                    rim.add(b)
            curve, _evaluate = ro._boundary_distance(coords, adjacency, rim)

            walk = {i: 0.0 for i in rim}
            heap = [(0.0, i) for i in rim]
            heapq.heapify(heap)
            while heap:
                d, i = heapq.heappop(heap)
                if d > walk.get(i, 1e30):
                    continue
                for j in adjacency[i]:
                    nd = d + (coords[i] - coords[j]).length
                    if nd < walk.get(j, 1e30):
                        walk[j] = nd
                        heapq.heappush(heap, (nd, j))

            kind = region.falloff_type
            out = {}
            for name, field in (("curve", curve), ("walk", walk)):
                top = max(field.values())
                f_eff = min(pre["feather_mm"] * 0.001, top)
                if f_eff <= 1e-9:
                    out[name] = 1.0
                    continue
                out[name] = _percentile([
                    abs(
                        ro._falloff(min(field.get(i, top), f_eff) / f_eff, kind)
                        - w
                    )
                    for i, w in weights.items()
                ])
            return out

        # ---------------------------------------------------------------- #
        # #49e: the falloff field itself.  Verified by experiment on
        # 2026-08-16 that reverting _region_weights_from_selection to the
        # pre-#49e Dijkstra left the ENTIRE battery green (failed_gates=[]),
        # so nothing here pinned the change that fixed the reported artifact.
        # These three gates are the discriminators.
        # ---------------------------------------------------------------- #
        obj, region, _pd, pre = painted_commit()
        arms = _candidate_fields(obj, region, pre)
        _gate(
            "w49e.field_is_curve_distance",
            arms["curve"] <= 0.01 and arms["walk"] >= 0.05,
            f"p95 deviation from distance-to-mollified-rim-CURVE="
            f"{arms['curve']:.4f} (must be <=0.01); from rim-VERTEX Dijkstra="
            f"{arms['walk']:.4f} (must be >=0.05, else the bake reverted)",
        )
        _gate(
            "w49e.rim_field_recovered",
            pre["rim_field"] is not None,
            "a freshly baked painted region reconstructs to its own "
            "closed-form field, so the commit can sample it",
        )
        # New vertices must SAMPLE the authored field, not interpolate the
        # coarse anchors.  Compared against both refinement paths run on the
        # undisplaced pre-commit mesh, where the field is defined.
        sampled = pre["mesh"].copy()
        interpolated = pre["mesh"].copy()
        ro._refine_footprint(
            sampled, pre["group"], pre["offset"], field=pre["rim_field"]
        )
        ro._refine_footprint(interpolated, pre["group"], pre["offset"])

        def _new_weights(mesh):
            out = []
            for v in mesh.vertices:
                if v.index < pre["n_orig"]:
                    continue
                for g in v.groups:
                    if g.group == pre["group"]:
                        out.append(g.weight)
                        break
            return sorted(out)

        shipped = _new_weights(obj.data)
        by_field = _new_weights(sampled)
        by_idw = _new_weights(interpolated)
        paths_differ = 0.0
        if by_field and by_idw:
            n = min(len(by_field), len(by_idw))
            paths_differ = _percentile([
                abs(by_field[i] - by_idw[i]) for i in range(n)
            ])
        matches_field = (
            bool(shipped)
            and len(shipped) == len(by_field)
            and max(
                (abs(a - b) for a, b in zip(shipped, by_field)), default=1.0
            ) <= 1e-9
        )
        _gate(
            "w49e.new_vertices_sample_the_field",
            matches_field and paths_differ >= 0.005,
            f"shipped {len(shipped)} new-vertex weights, field path "
            f"{len(by_field)}, IDW path {len(by_idw)}; shipped==field:"
            f"{matches_field}; the two paths differ by p95 {paths_differ:.4f} "
            f"(must be >=0.005, else field= is a no-op)",
        )
        bpy.data.meshes.remove(sampled)
        bpy.data.meshes.remove(interpolated)
        bpy.data.meshes.remove(pre["mesh"])
        _delete(obj)

        # smooth-after-commit: the sculpted smooth must not spike.
        obj, region, pre_dih, pre = painted_commit()
        w = _group_weights(obj, region.surface_mask)
        fp = {i for i, wt in w.items() if wt > 1e-5}
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="VERT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        for i in fp:
            bm.verts[i].select = True
        bmesh.update_edit_mesh(obj.data)
        bpy.ops.mesh.vertices_smooth(factor=0.5, repeat=5)
        bpy.ops.object.mode_set(mode="OBJECT")
        post_dih = _dihedral_map(obj, fp)
        worsened = sum(
            1 for key, a in post_dih.items()
            if a > 60.0 and key in pre_dih and pre_dih[key] <= 45.0
        )
        _gate(
            "w49.smooth_after_commit",
            worsened <= _T["quality"]["smooth_new_spikes"],
            f"worsened_preexisting={worsened} after Laplacian 0.5x5",
        )
        sig_a = _topo_sig(obj.data)
        bpy.data.meshes.remove(pre["mesh"])
        _delete(obj)

        # #49f: the SHIPPED Smooth Area operator on a committed correction.
        # bpy.ops.mesh.vertices_smooth stopped dead at the painted border and
        # wrote that discontinuity into the surface (measured on the A-model
        # 20 mm region: 1.66 mm step, 6.3 deg mean crease along the painted
        # outline, convex speed bumps 87 -> 123, worst core point down to 85%
        # of the authored depth).  A polish tool may not step at its own
        # border, may not move untouched anatomy, and may not eat the
        # correction.
        obj, region, _pd, pre = painted_commit()
        w = _group_weights(obj, region.surface_mask)
        member = {i for i, wt in w.items() if wt > 1e-5}
        me = obj.data
        before = [v.co.copy() for v in me.vertices]
        pre_ridges = _convex_ridges(obj, w)
        # Realized correction depth against the UNDISPLACED surface, before
        # and after the polish.  The operator tells the orthotist "correction
        # depth preserved" on every run; until now nothing verified it.
        undisplaced = BVHTree.FromPolygons(
            pre["coords"], pre["polys"], all_triangles=True
        )
        core = [i for i, wt in w.items() if wt >= 0.95]

        def _core_depth(mesh):
            out = []
            for i in core:
                loc, _n, _idx, _d = undisplaced.find_nearest(
                    mesh.vertices[i].co
                )
                if loc is not None:
                    out.append((mesh.vertices[i].co - loc).length * 1000.0)
            return sorted(out)

        depth_before = _core_depth(me)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(me)
        for f in bm.faces:
            if all(v.index in member for v in f.verts):
                f.select = True
        bmesh.update_edit_mesh(me)
        settings.select_smooth_factor = 0.5
        settings.select_smooth_iters = 5
        bpy.ops.rigo.smooth_selection()
        bpy.ops.object.mode_set(mode="OBJECT")
        me = obj.data
        # The invariant is that the operator has no CLIFF at the edge of its
        # own influence — measured where it actually stops, not at the paint
        # border (#49h: the influence now decays a few rows PAST the paint so
        # a correction can blend into the body).  Reach is bounded too.
        shifted = {
            i for i in range(len(before))
            if (me.vertices[i].co - before[i]).length > 1e-9
        }
        step = 0.0
        for e in me.edges:
            a, b = e.vertices
            if (a in shifted) == (b in shifted):
                continue
            inner = a if a in shifted else b
            step = max(step, (me.vertices[inner].co - before[inner]).length)
        # The blend must be BOUNDED in millimetres, not in vertex count: a
        # small region legitimately blends into a proportionally larger patch
        # of surrounding surface, which is the whole point (#49h).
        inside_tree = kdtree.KDTree(len(member))
        for i in member:
            inside_tree.insert(me.vertices[i].co, i)
        inside_tree.balance()
        reach = 0.0
        stray = 0
        for i in shifted:
            if i in member:
                continue
            stray += 1
            _co, _idx, d = inside_tree.find(me.vertices[i].co)
            reach = max(reach, d)
        post_ridges = _convex_ridges(obj, w)
        _gate(
            "w49f.smooth_area_no_border_step",
            step * 1000.0 <= 0.15 and reach * 1000.0 <= 40.0,
            f"influence_edge_step={step*1000.0:.4f}mm blend_reach="
            f"{reach*1000.0:.1f}mm moved={len(shifted)} "
            f"(region has {len(member)}, blended beyond it={stray})",
        )
        # Visible bumps (>30 deg) may not increase; the sub-visible 10-30 deg
        # band is allowed to move within half again, because smoothing an
        # already-clean wall inevitably redistributes small undulations
        # (#49h measured: >30 deg 10 -> 1 while the >10 deg count went
        # 87 -> 120).  Gating the small band as a hard ceiling would forbid
        # the blend the orthotist asked for while forbidding nothing visible.
        _gate(
            "w49f.smooth_area_no_new_bumps",
            post_ridges[1] <= pre_ridges[1]
            and post_ridges[0] <= max(8, int(pre_ridges[0] * 1.5)),
            f"convex ridges >10deg {pre_ridges[0]} -> {post_ridges[0]} "
            f"(ceiling {max(8, int(pre_ridges[0] * 1.5))}), "
            f">30deg {pre_ridges[1]} -> {post_ridges[1]}",
        )
        depth_after = _core_depth(obj.data)
        med_before = depth_before[len(depth_before) // 2] if depth_before else 0.0
        med_after = depth_after[len(depth_after) // 2] if depth_after else 0.0
        # The discriminator here is the WORST-POINT floor, not the median.
        # Measured on the A model, the pre-#49f smoother left the median at
        # 98.6% of authored while collapsing the worst core point to 85% —
        # so a median-only gate would have passed the very defect this
        # exists to catch.  The median bound is a sanity ceiling, set at the
        # same 5% scale as the contract's own +/-10% amount tolerance;
        # measured on this fixture the shipped smoother costs 3.2% of the
        # median and IMPROVES the worst point.
        _gate(
            "w49h.smooth_area_keeps_depth",
            bool(depth_before)
            and med_after >= 0.95 * med_before
            and depth_after[0] >= 0.90 * depth_before[0],
            f"core depth median {med_before:.2f} -> {med_after:.2f}mm "
            f"({100.0 * med_after / max(med_before, 1e-9):.1f}%), worst point "
            f"{depth_before[0]:.2f} -> {depth_after[0]:.2f}mm "
            f"({100.0 * depth_after[0] / max(depth_before[0], 1e-9):.1f}%, "
            f"floor 90% — the pre-#49f smoother scored 85% here)",
        )
        # The blend deliberately reaches past the paint (#49h), so how FAR a
        # single untouched vertex may be displaced needs its own ceiling —
        # the first ring outside the paint is smoothed at 98% of full
        # strength, and nothing else bounds its travel.
        outside_travel = max(
            (
                (obj.data.vertices[i].co - before[i]).length
                for i in shifted if i not in member
            ),
            default=0.0,
        )
        _gate(
            "w49h.smooth_area_outside_travel",
            outside_travel * 1000.0 <= 2.0,
            f"furthest untouched vertex moved {outside_travel*1000.0:.3f}mm "
            f"(ceiling 2.0)",
        )
        bpy.data.meshes.remove(pre["mesh"])
        _delete(obj)

        # determinism: an identical refined commit is bit-identical.
        obj, region, _pd, pre = painted_commit()
        sig_b = _topo_sig(obj.data)
        _gate("w49.refine_determinism", sig_a == sig_b,
              f"sig_a={sig_a} sig_b={sig_b}")
        # #49e safety branch: a region baked by an OLDER build carries
        # Dijkstra weights, and the reconstruction must REFUSE to treat them
        # as its own field — otherwise reopening a saved case silently
        # re-authors the correction.  Fired once in a probe; gated here.
        legacy = pre["mesh"]
        weights = _group_weights(obj, region.surface_mask)
        weights = {
            i: w for i, w in weights.items() if i < len(legacy.vertices)
        }
        adjacency = {i: [] for i in weights}
        rim = set()
        for edge in legacy.edges:
            a, b = edge.vertices
            a_in, b_in = a in adjacency, b in adjacency
            if a_in and b_in:
                adjacency[a].append(b)
                adjacency[b].append(a)
            elif a_in:
                rim.add(a)
            elif b_in:
                rim.add(b)
        walk = {i: 0.0 for i in rim}
        heap = [(0.0, i) for i in rim]
        heapq.heapify(heap)
        while heap:
            d, i = heapq.heappop(heap)
            if d > walk.get(i, 1e30):
                continue
            for j in adjacency[i]:
                nd = d + (
                    legacy.vertices[i].co - legacy.vertices[j].co
                ).length
                if nd < walk.get(j, 1e30):
                    walk[j] = nd
                    heapq.heappush(heap, (nd, j))
        top = max(walk.values())
        f_eff = min(0.010, top)
        group = obj.vertex_groups.get(region.surface_mask)
        stand_in = bpy.data.objects.new("QA legacy region", legacy)
        bpy.context.scene.collection.objects.link(stand_in)
        legacy_group = stand_in.vertex_groups.new(name=region.surface_mask)
        for i in weights:
            legacy_group.add(
                [i],
                max(
                    ro._falloff(
                        min(walk.get(i, top), f_eff) / f_eff,
                        region.falloff_type,
                    ),
                    1e-6,
                ),
                "REPLACE",
            )
        rejected = ro._authored_rim_field(
            legacy, legacy_group.index, region.falloff_type
        )
        _gate(
            "w49e.legacy_region_not_reauthored",
            rejected is None,
            "a Dijkstra-baked (older build) region is REFUSED by the "
            "reconstruction, so its saved field is left alone: got "
            + ("None" if rejected is None
               else "a field - it would be silently re-authored"),
        )
        bpy.data.objects.remove(stand_in, do_unlink=True)
        _delete(obj)

        # overlap masks (audit B3): committing region A must preserve an
        # overlapping uncommitted region B's mask integral.
        obj = _import_scan(_SCAN)
        me = obj.data
        bpy.context.scene.cursor.location = obj.matrix_world @ me.vertices[9000].co
        settings.region_radius = 30.0
        settings.region_magnitude = 15.0
        settings.region_kind = "PRESSURE"
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add_circle()
        region_a = obj.rigo_regions[obj.rigo_region_index]
        wa = _group_weights(obj, region_a.surface_mask)
        near = min(
            (i for i, wt in wa.items() if 0.3 < wt < 0.6),
            default=next(iter(wa)),
        )
        bpy.context.scene.cursor.location = obj.matrix_world @ me.vertices[near].co
        settings.region_magnitude = 5.0
        bpy.ops.rigo.region_add_circle()
        region_b = obj.rigo_regions[obj.rigo_region_index]
        wb_before = _group_weights(obj, region_b.surface_mask)
        integral_before = sum(wb_before.values())
        obj.rigo_region_index = 0
        bpy.ops.rigo.region_apply()
        wb_after = _group_weights(obj, region_b.surface_mask)
        # Density-independent oracle: B's FIELD is preserved when every
        # surviving original vertex keeps its weight (new verts merely
        # sample the same field finer — a raw integral grows with density).
        drift = max(
            (abs(wb_after.get(i, 0.0) - w0) for i, w0 in wb_before.items()),
            default=1.0,
        )
        _gate(
            "w49.overlap_mask_preserved",
            drift <= 0.02 and len(wb_after) >= len(wb_before),
            f"max original-vert weight drift={drift:.4f} "
            f"(integral {integral_before:.1f}->{sum(wb_after.values()):.1f}) "
            f"verts {len(wb_before)}->{len(wb_after)}",
        )
        _delete(obj)

        # already-dense scan: refinement is a no-op by construction.
        g = _make_grid("QA_W49_DENSE", 0.3, 150, 0.3, 21)
        seed = _nearest_vertex(g.data, Vector((0, 0, 0)))
        bpy.context.scene.cursor.location = g.matrix_world @ g.data.vertices[seed].co
        settings.region_radius = 30.0
        settings.region_magnitude = 15.0
        settings.region_kind = "PRESSURE"
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add_circle()
        n0 = len(g.data.vertices)
        bpy.ops.rigo.region_apply()
        region = g.rigo_regions[g.rigo_region_index]
        _gate(
            "w49.dense_noop",
            len(g.data.vertices) == n0 and region.refined_added == 0,
            f"verts {n0}->{len(g.data.vertices)} "
            f"declared={region.refined_added}",
        )
        _delete(g)

        # #49d: the amount must SCALE the refinement, never fall off a
        # cliff — a 20 mm pad on the A-model waist used to fall back to the
        # staircase, and sculpt-smoothing the fallback tore a crown of
        # spikes (orthotist screenshots; their config: 20 mm / feather 20).
        # The 2:1 steep extreme (20/10) legitimately warns-and-falls-back
        # on this wrinkled crease zone; the clinical big-pad shape (feather
        # comparable to amount, Rigo pad proportions) must commit REFINED.
        obj = _import_scan(_A_SCAN)
        me = obj.data
        cos = [obj.matrix_world @ v.co for v in me.vertices]
        z_lo = min(c.z for c in cos)
        z_hi = max(c.z for c in cos)
        y_lo, y_hi = min(c.y for c in cos), max(c.y for c in cos)
        x_lo, x_hi = min(c.x for c in cos), max(c.x for c in cos)
        anchor = Vector((
            (x_lo + x_hi) * 0.5,
            y_lo + 0.10 * (y_hi - y_lo),
            z_lo + 0.45 * (z_hi - z_lo),
        ))
        seed = _nearest_vertex(me, anchor)
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
        settings.region_magnitude = 20.0
        settings.region_feather = 20.0
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add()
        region = obj.rigo_regions[obj.rigo_region_index]
        pre_dih = _dihedral_map(
            obj, set(_group_weights(obj, region.surface_mask))
        )
        st = bpy.ops.rigo.region_apply()
        _gate(
            "w49.amount20_refined",
            st == {"FINISHED"} and region.refined_added > 0,
            f"st={st} refined_added={region.refined_added}",
        )
        w = _group_weights(obj, region.surface_mask)
        fp = {i for i, wt in w.items() if wt > 1e-5}
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="VERT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        for i in fp:
            bm.verts[i].select = True
        bmesh.update_edit_mesh(obj.data)
        bpy.ops.mesh.vertices_smooth(factor=0.5, repeat=5)
        bpy.ops.object.mode_set(mode="OBJECT")
        post_dih = _dihedral_map(obj, fp)
        worsened = sum(
            1 for key, a in post_dih.items()
            if a > 60.0 and key in pre_dih and pre_dih[key] <= 45.0
        )
        _gate(
            "w49.amount20_smooth_after",
            worsened <= _T["quality"]["smooth_new_spikes"],
            f"worsened_preexisting={worsened} after Laplacian 0.5x5",
        )
        _delete(obj)

    def roundtrip_case():
        # Precision contract (#48 hardening item 8): mask weights survive the
        # float32 vertex-group store with their MEMBERSHIP intact (> 0.0),
        # across repeated write/read cycles; library JSON round-trips exactly.
        g = _make_grid("QA_RT", 0.05, 4, 0.0, 9)
        vg = g.vertex_groups.new(name="QA_RT_G")
        values = [0.0, 5e-7, 1e-6, 2e-6, 0.005, 0.0051, 0.99, 1.0]
        ok = True
        detail = []
        stored = {i: v for i, v in enumerate(values)}
        for _cycle in range(3):
            for i, v in stored.items():
                vg.add([i], v, "REPLACE")
            read = {}
            for i in stored:
                for gref in g.data.vertices[i].groups:
                    if gref.group == vg.index:
                        read[i] = gref.weight
                        break
            for i, v in stored.items():
                got = read.get(i, 0.0)
                if v > 0.0 and not got > 0.0:
                    ok = False
                    detail.append(f"v={v} lost membership (read {got})")
                if abs(got - v) > 1e-6 + v * 1e-6:
                    ok = False
                    detail.append(f"v={v} drifted to {got}")
            stored = read
        entry = {
            "id": "QA_RT_STYLE", "label": "QA RT Style", "kind": "PRESSURE",
            "magnitude_mm": 8.0, "falloff": "SMOOTH",
            "samples": [[0.0, 0.0, 1.0], [3.0, 0.0, 0.5], [0.0, 3.0, 0.5]],
            "sample_radius_mm": 3.0,
            "normal_tolerance_mm": 15.0,
            "field": {"cell_mm": 1.0, "x0": 0.0, "y0": 0.0, "nx": 2, "ny": 1,
                      "values": values},
            "requires_orthotist_review": True, "schema_version": 2,
        }
        lib.upsert_entry(entry)
        for _cycle in range(3):
            back = lib.get_entry("QA_RT_STYLE")
            if back is None or back["field"]["values"] != values:
                ok = False
                detail.append("library JSON drifted")
                break
            lib.upsert_entry(dict(back))
            lib.load_library(force=True)
        lib.delete_entry("QA_RT_STYLE")
        _gate("serialization_roundtrip", ok, "; ".join(detail) or "3 cycles clean")
        _delete(g)

    try:
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                capture_output=True, text=True, timeout=10,
            ).stdout.strip() or "unknown"
        except Exception:  # noqa: BLE001
            commit = "unknown"
        _mark(
            f"provenance commit={commit} date={time.strftime('%Y-%m-%d %H:%M')} "
            f"blender={bpy.app.version_string}"
        )
        _mark("phase=start")
        _safe("scan", scan_cases)
        _safe("imports", import_cases)
        _safe("patient", patient_cases)
        _safe("flat", flat_cases)
        _safe("oppwall", lambda: oppwall_cases(ro))
        _safe("foldunit", lambda: fold_unit_case(ro))
        _safe("flipconfirm", lambda: flip_confirm_unit_case(ro))
        _safe("w2mirror", wave2_mirror_case)
        _safe("w2horseshoe", wave2_horseshoe_case)
        _safe("w2size", wave2_size_case)
        _safe("w49", w49_cases)
        _safe("roundtrip", roundtrip_case)
        _mark(f"total_time={time.perf_counter() - t_all:.1f}s")
        failed = [k for k, v in _GATES.items() if not v]
        _mark(f"failed_gates={failed}")
        _mark(f"PASS={not failed and len(_GATES) > 20}")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")
    finally:
        for e in list(lib.load_library(force=True)):
            if e.get("label") in _STYLE_LABELS:
                lib.delete_entry(e["id"])
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
