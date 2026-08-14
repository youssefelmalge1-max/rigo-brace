"""Contract-gated quality test for Pressure/Expansion regions + style library.

Implements knowledge/region_quality_contract.md (#48): validity, smoothness,
amount, feather, library parity, resolution robustness, evaluated-surface
consistency, determinism and performance — as hard PASS/FAIL gates, not
appearance.  Writes regionqualtest_result.txt (last line PASS=True/False).

GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools\regionqualtest.py
"""

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
             amount_mm, expect_sign, nonman0, pre_cross=frozenset()):
    me = obj.data
    adj = _adjacency(me)
    fp = {i for i, w in weights.items() if w > 1e-5}
    # Topology-tolerant: vertices born after the pre-snapshot (refined
    # commits, #49) carry no per-index history — they are measured by the
    # quality block and the analytic-profile oracle, never by index maps.
    d = {}
    for v in me.vertices:
        b = before.get(v.index)
        if b is not None:
            d[v.index] = (v.co - b).dot(before_n[v.index]) * 1000.0

    holes = 0
    for i in fp | {n for i in fp for n in adj[i]}:
        if weights.get(i, 0.0) < 0.1:
            if sum(1 for n in adj[i] if weights.get(n, 0.0) > 0.5) >= 3:
                holes += 1

    osc = []
    for i in fp:
        if i in d and adj[i]:
            known = [d[n] for n in adj[i] if n in d]
            if known:
                osc.append(abs(d[i] - sum(known) / len(known)))
    osc_max = max(osc) if osc else 0.0
    osc_mean = (sum(osc) / len(osc)) if osc else 0.0

    rev = 0
    rev_tol = _T["feather"]["rev_tol_mm"]
    for e in me.edges:
        a, b = e.vertices
        if a not in d or b not in d:
            continue
        wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
        if wa == wb or (wa == 0.0 and wb == 0.0):
            continue
        if (wa - wb) * (abs(d[a]) - abs(d[b])) < 0 and abs(abs(d[a]) - abs(d[b])) > rev_tol:
            rev += 1

    core = [abs(d[i]) for i, w in weights.items() if w > 0.9 and i in d]
    core_med = statistics.median(core) if core else 0.0

    # Weight-decile profile: mean |d| must rise monotonically with weight
    # (shape-agnostic form of the contract's transition-profile clause).
    bins = {}
    for i, w in weights.items():
        if w > 0.0 and i in d:
            bins.setdefault(min(9, int(w * 10.0)), []).append(abs(d[i]))
    profile = [sum(v) / len(v) for _k, v in sorted(bins.items())]
    decile_tol = _T["feather"]["decile_rev_tol_mm"]
    decile_rev = sum(
        1 for a, b in zip(profile, profile[1:]) if b < a - decile_tol
    )

    count_ok = (
        len(me.vertices) == len(before) and len(me.polygons) == len(before_fn)
    )
    outside = max(
        (abs(d[v.index]) for v in me.vertices
         if v.index not in weights and v.index in d),
        default=0.0,
    )
    sign_ok = all(
        (d[i] * expect_sign) >= -0.05
        for i in fp if i in d and abs(d[i]) > 0.1
    )

    post_dih = _dihedral_map(obj, fp)
    new_spikes = sum(
        1 for key, a in post_dih.items()
        if a > 60.0 and pre_dih.get(key, 0.0) <= 45.0
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
    quality = {
        "stretch_max": max(stretch) if stretch else 0.0,
        "stretch_gt15": sum(1 for s in stretch if s > 1.5),
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
        f">1.5x:{quality['stretch_gt15']} aspect_p95={quality['aspect_p95']:.2f} "
        f">8:{quality['aspect_gt8']} max_edge={quality['max_edge_mm']:.2f}mm"
    )
    return {
        "quality": quality,
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
    if qc.get("enforced"):
        q = m["quality"]
        _gate(
            f"{tag}.quality",
            q["stretch_max"] <= qc["stretch_max"]
            and q["stretch_gt15"] <= qc["stretch_gt15_max"]
            and (q["aspect_p95_pre"] <= 0.0
                 or q["aspect_p95"]
                 <= qc["aspect_p95_factor"] * q["aspect_p95_pre"]),
            f"stretch={q['stretch_max']:.2f} gt15={q['stretch_gt15']} "
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
    eff_d = {i for i, w in m_direct["weights"].items() if w > 0.05}
    eff_i = {i for i, w in m_import["weights"].items() if w > 0.05}
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
    before, before_n, before_fn = _snapshot(obj)
    try:
        st = bpy.ops.rigo.region_apply()
    except RuntimeError as exc:
        st = {"CANCELLED"}
        _mark(f"[{tag}] refused: {exc}")
    if st == {"FINISHED"}:
        weights = _group_weights(obj, mask)
        m = _measure(tag, obj, before, before_n, before_fn, pre_dih,
                     weights, amount, -1.0, nonman0, pre_cross)
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


def _paint_patch(obj, seed_face, count):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
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
    before, before_n, before_fn = _snapshot(obj)
    if not commit:
        return None, weights
    bpy.ops.rigo.region_apply()
    # Re-read AFTER commit: once commits refine topology (#49) the vertex
    # group is the only self-consistent weight source for the final mesh.
    weights = _group_weights(obj, region.surface_mask)
    sign = -1.0 if kind == "PRESSURE" else 1.0
    m = _measure(tag, obj, before, before_n, before_fn, pre_dih, weights,
                 amount, sign, nonman0, pre_cross)
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
    before, before_n, before_fn = _snapshot(obj)
    t0 = time.perf_counter()
    st_apply = bpy.ops.rigo.region_apply()
    t_commit = time.perf_counter() - t0
    if st_apply != {"FINISHED"}:
        _gate(f"{tag}.commit", False, f"returned {st_apply}")
        return None
    weights = _group_weights(obj, region.surface_mask)
    sign = -1.0 if region.kind == "PRESSURE" else 1.0
    m = _measure(tag, obj, before, before_n, before_fn, pre_dih, weights,
                 region.magnitude_mm, sign, nonman0, pre_cross)
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
        for tag, seed_face, gated in (
            ("paint15", None, True),        # patch around vertex 9000
            ("paint15_hostile", 5000, False),
        ):
            obj = _import_scan(_SCAN)
            if seed_face is None:
                for p in obj.data.polygons:
                    if 9000 in p.vertices:
                        seed_face = p.index
                        break
            _paint_patch(obj, seed_face, 300)
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
                before, before_n, before_fn = _snapshot(obj)
                bpy.ops.rigo.region_apply()
                m = _measure(tag, obj, before, before_n, before_fn, pre_dih,
                             weights, 15.0, -1.0, nonman0, pre_cross)
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

        for tag, ratio in (("import_decim065", 0.65), ("import_decim030", 0.30)):
            obj = _import_scan(_SCAN)
            mod = obj.modifiers.new("QA_DEC", "DECIMATE")
            mod.ratio = ratio
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=mod.name)
            _run_import(tag, obj, style, cursor, 15.0, 30.0)
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
                before, before_n, before_fn = _snapshot(obj)
                bpy.ops.rigo.region_apply()
                m = _measure(f"{tag}_b", obj, before, before_n, before_fn,
                             pre_dih, weights, amount, -1.0, nonman0,
                             pre_cross)
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
            before, before_n, before_fn = _snapshot(obj)
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
            and abs(ro._FOLD_PRE_DOT - _T["fold"]["pre_dot"]) < 1e-9,
            f"prod=({ro._WALL_CLEARANCE_MM},{ro._FOLD_DOT},{ro._FOLD_PRE_DOT})",
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
        before, before_n, before_fn = _snapshot(obj)
        st = bpy.ops.rigo.region_apply()
        if st == {"FINISHED"}:
            m = _measure("mirror_commit", obj, before, before_n, before_fn,
                         pre_dih, w_m, 8.0, 1.0, nonman0, pre_cross)
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
        _safe("w2mirror", wave2_mirror_case)
        _safe("w2horseshoe", wave2_horseshoe_case)
        _safe("w2size", wave2_size_case)
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
