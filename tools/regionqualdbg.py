"""Geometry-quality probe for the reusable Pressure/Expansion region library.

Measures — with numbers, not visuals — every stage of the correction path on a
matrix of fixtures (dense scan, patient scan, flat grids, decimated targets):

  weight field   -> max/mean edge weight jump, holes, Voronoi provenance
  displacement   -> signed mm field, one-ring Laplacian oscillation, monotonicity
  surface        -> dihedral spikes, inverted/degenerate faces, self-intersections
  amount         -> core median vs requested mm, outside-footprint leakage

Writes regionqualdbg_result.txt incrementally.  GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools\regionqualdbg.py
"""

import math
import random
import statistics
import time
import traceback

import bpy
import bmesh
import importlib
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils import kdtree

_OUT = r"C:\Projects\Blender Add-on Braces\regionqualdbg_result.txt"
_SCAN = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_PATIENT = r"C:\Projects\Blender Add-on Braces\A type model.stl"
_TRIES = {"n": 0}
_log = []
_STYLE_LABELS = (
    "QA Qual Scan Style", "QA Qual Flat Style",
    "QA Qual Pre Style", "QA Qual Patient Style",
)


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


# --------------------------------------------------------------------------- #
# Mesh helpers
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


def _mesh_stats(tag, obj):
    me = obj.data
    total = 0.0
    for e in me.edges:
        a, b = e.vertices
        total += (me.vertices[a].co - me.vertices[b].co).length
    mean_mm = total / len(me.edges) * 1000.0 if me.edges else 0.0
    _mark(
        f"[{tag}] mesh: verts={len(me.vertices)} faces={len(me.polygons)} "
        f"mean_edge={mean_mm:.2f}mm"
    )


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


def _footprint_faces(me, fp):
    return [p for p in me.polygons if any(vi in fp for vi in p.vertices)]


def _dihedral_stats(obj, fp):
    """Max/mean dihedral (rad->deg) over edges whose both faces touch fp."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.edges.ensure_lookup_table()
    angles = []
    for e in bm.edges:
        if len(e.link_faces) != 2:
            continue
        if not any(v.index in fp for v in e.verts):
            continue
        try:
            angles.append(abs(e.calc_face_angle()))
        except ValueError:
            angles.append(math.pi)  # degenerate
    bm.free()
    if not angles:
        return 0.0, 0.0, 0
    deg = [math.degrees(a) for a in angles]
    return max(deg), sum(deg) / len(deg), sum(1 for a in deg if a > 60.0)


def _self_intersections(obj, fp):
    """Count intersecting non-adjacent face pairs among footprint faces."""
    me = obj.data
    faces = _footprint_faces(me, fp)
    if not faces:
        return 0
    verts = [v.co for v in me.vertices]
    polys = [tuple(p.vertices) for p in faces]
    tree = BVHTree.FromPolygons(verts, polys, all_triangles=True)
    pairs = tree.overlap(tree)
    hits = set()
    for a, b in pairs:
        if a == b:
            continue
        if set(polys[a]) & set(polys[b]):
            continue
        hits.add((min(a, b), max(a, b)))
    return len(hits)


def _measure(tag, obj, before, before_n, before_fn, weights, amount_mm,
             expect_sign):
    """Full metric block after a committed correction. Logs one line each."""
    me = obj.data
    adj = _adjacency(me)
    fp = {i for i, w in weights.items() if w > 1e-5}
    d = {}
    for v in me.vertices:
        delta = v.co - before[v.index]
        d[v.index] = delta.dot(before_n[v.index]) * 1000.0

    # Weight-field roughness.
    wj = []
    for e in me.edges:
        a, b = e.vertices
        wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
        if wa > 0.0 or wb > 0.0:
            wj.append(abs(wa - wb))
    wj_max = max(wj) if wj else 0.0
    wj_mean = (sum(wj) / len(wj)) if wj else 0.0
    holes = 0
    for i in fp | {n for i in fp for n in adj[i]}:
        wi = weights.get(i, 0.0)
        if wi < 0.1:
            big = sum(1 for n in adj[i] if weights.get(n, 0.0) > 0.5)
            if big >= 3:
                holes += 1

    # Displacement oscillation (one-ring Laplacian of the signed field).
    osc = []
    for i in fp:
        if not adj[i]:
            continue
        m = sum(d[n] for n in adj[i]) / len(adj[i])
        osc.append(abs(d[i] - m))
    osc_max = max(osc) if osc else 0.0
    osc_mean = (sum(osc) / len(osc)) if osc else 0.0

    # Monotonicity of |d| against weight across edges.
    rev = 0
    checked = 0
    for e in me.edges:
        a, b = e.vertices
        wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
        if wa == wb or (wa == 0.0 and wb == 0.0):
            continue
        checked += 1
        if (wa - wb) * (abs(d[a]) - abs(d[b])) < 0 and abs(abs(d[a]) - abs(d[b])) > 0.2:
            rev += 1

    # Amount fidelity.
    core = [abs(d[i]) for i, w in weights.items() if w > 0.95]
    core_med = statistics.median(core) if core else 0.0
    peak = max((abs(d[i]) for i in fp), default=0.0)
    sign_ok = all(
        (d[i] * expect_sign) >= -0.05 for i in fp if abs(d[i]) > 0.1
    )
    outside = max(
        (abs(d[v.index]) for v in me.vertices if v.index not in weights),
        default=0.0,
    )

    # Surface integrity.
    dih_max, dih_mean, dih_over60 = _dihedral_stats(obj, fp)
    inverted = sum(
        1 for p in _footprint_faces(me, fp)
        if p.normal.dot(before_fn[p.index]) < 0.0
    )
    degen = sum(1 for p in _footprint_faces(me, fp) if p.area < 1e-12)
    selfx = _self_intersections(obj, fp)

    _mark(
        f"[{tag}] verts={len(fp)} amount={amount_mm}mm | "
        f"core_med={core_med:.2f} peak={peak:.2f} outside={outside:.4f} sign_ok={sign_ok}"
    )
    _mark(
        f"[{tag}] weight: edge_jump max={wj_max:.3f} mean={wj_mean:.4f} holes={holes}"
    )
    _mark(
        f"[{tag}] displacement: osc_max={osc_max:.3f}mm osc_mean={osc_mean:.4f}mm "
        f"monotone_rev={rev}/{checked}"
    )
    _mark(
        f"[{tag}] surface: dihedral max={dih_max:.1f}deg mean={dih_mean:.2f} "
        f">60deg={dih_over60} inverted={inverted} degen={degen} selfx={selfx}"
    )
    return {
        "d": d, "fp": fp, "wj_max": wj_max, "holes": holes,
        "osc_max": osc_max, "osc_mean": osc_mean, "core_med": core_med,
        "peak": peak, "selfx": selfx, "inverted": inverted,
        "dih_max": dih_max, "over60": dih_over60,
    }


def _pre_dihedral(tag, obj, fp):
    dih_max, dih_mean, over = _dihedral_stats(obj, fp)
    _mark(f"[{tag}] pre-surface: dihedral max={dih_max:.1f} mean={dih_mean:.2f} >60deg={over}")


# --------------------------------------------------------------------------- #
# Region construction helpers
# --------------------------------------------------------------------------- #
def _geodesic_weights(me, seed, radius_m):
    import heapq
    neighbors = [[] for _ in range(len(me.vertices))]
    for e in me.edges:
        a, b = e.vertices
        length = (me.vertices[a].co - me.vertices[b].co).length
        neighbors[a].append((b, length))
        neighbors[b].append((a, length))
    dist = {seed: 0.0}
    heap = [(0.0, seed)]
    while heap:
        dcur, i = heapq.heappop(heap)
        if dcur > dist.get(i, 1e30):
            continue
        for j, length in neighbors[i]:
            nd = dcur + length
            if nd <= radius_m and nd < dist.get(j, 1e30):
                dist[j] = nd
                heapq.heappush(heap, (nd, j))
    weights = {}
    for i, dcur in dist.items():
        t = 1.0 - dcur / radius_m
        weights[i] = t * t * (3.0 - 2.0 * t)
    return {i: w for i, w in weights.items() if w > 0.0}


def _apply_displace(obj, weights, amount_mm, sign):
    vg = obj.vertex_groups.new(name="QA_CTRL")
    for i, w in weights.items():
        vg.add([i], w, "REPLACE")
    mod = obj.modifiers.new("QA_CTRL_DISP", "DISPLACE")
    mod.vertex_group = "QA_CTRL"
    mod.direction = "NORMAL"
    mod.mid_level = 0.0
    mod.strength = sign * amount_mm * 0.001
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)


def _smoothed_normal_displace(obj, weights, amount_mm, sign):
    """Manual displacement along a 2-ring averaged normal field."""
    me = obj.data
    adj = _adjacency(me)
    normals = {v.index: v.normal.copy() for v in me.vertices}
    fp = set(weights)
    sm = {}
    for i in fp:
        acc = normals[i].copy()
        seen = {i}
        ring1 = [n for n in adj[i]]
        for n in ring1:
            if n not in seen:
                acc += normals[n]
                seen.add(n)
        for n in ring1:
            for n2 in adj[n]:
                if n2 not in seen:
                    acc += normals[n2]
                    seen.add(n2)
        sm[i] = acc.normalized() if acc.length > 1e-12 else normals[i]
    for i, w in weights.items():
        me.vertices[i].co += sm[i] * (sign * amount_mm * 0.001 * w)
    me.update()


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


def _make_grid(name, size_m, divisions, jitter_frac, seed):
    rng = random.Random(seed)
    bm = bmesh.new()
    bmesh.ops.create_grid(
        bm, x_segments=divisions, y_segments=divisions, size=size_m * 0.5
    )
    bmesh.ops.triangulate(bm, faces=bm.faces)
    spacing = size_m / divisions
    for v in bm.verts:
        if len(v.link_edges) >= 6:  # interior only
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


def _region_ops_module():
    return importlib.import_module(
        "bl_ext.user_default.rigo_brace.operators.region_ops"
    )


def _import_provenance(tag, scan, entry, cursor_world):
    """Re-derive the import mapping to expose the sample->vertex transfer."""
    ro = _region_ops_module()
    target, normal = ro._target_surface(scan, cursor_world)
    if target is None:
        _mark(f"[{tag}] provenance: no target surface")
        return
    side, up, outward = ro._surface_frame(normal)
    samples = entry["samples"]
    tree = kdtree.KDTree(len(samples))
    for idx, s in enumerate(samples):
        tree.insert((s[0], s[1], 0.0), idx)
    tree.balance()
    radius = max(float(entry["sample_radius_mm"]), ro._mesh_spacing_mm(scan) * 1.75)
    nlimit = float(entry["normal_tolerance_mm"])
    max_r2d = max(math.hypot(s[0], s[1]) for s in samples)
    owner = {}
    culled_normal = 0
    culled_radius_inside = 0
    for v in scan.data.vertices:
        world = scan.matrix_world @ v.co
        rel = world - target
        noff = abs(rel.dot(outward)) * 1000.0
        u, w2 = rel.dot(side) * 1000.0, rel.dot(up) * 1000.0
        r2d = math.hypot(u, w2)
        if noff > nlimit:
            if r2d < max_r2d * 0.9:
                culled_normal += 1
            continue
        _co, sidx, dist = tree.find((u, w2, 0.0))
        if dist <= radius:
            owner[v.index] = (sidx, dist)
        elif r2d < max_r2d * 0.8:
            culled_radius_inside += 1
    # Edge jumps across Voronoi-cell borders.
    jumps = []
    for e in scan.data.edges:
        a, b = e.vertices
        if a in owner and b in owner and owner[a][0] != owner[b][0]:
            jumps.append(abs(samples[owner[a][0]][2] - samples[owner[b][0]][2]))
    big = sum(1 for j in jumps if j > 0.15)
    n_samples_used = len({o[0] for o in owner.values()})
    _mark(
        f"[{tag}] provenance: matched={len(owner)} samples_used={n_samples_used}/"
        f"{len(samples)} accept_radius={radius:.2f}mm normal_tol={nlimit:.1f}mm | "
        f"culled_inside: normal={culled_normal} radius={culled_radius_inside} | "
        f"voronoi_edge_jumps>{0.15}: {big}/{len(jumps)} "
        f"max={max(jumps) if jumps else 0.0:.3f}"
    )


# --------------------------------------------------------------------------- #
# Cases
# --------------------------------------------------------------------------- #
def _commit_active_region(obj):
    bpy.ops.rigo.region_apply()


def _case_direct_circle(tag, path, amount, kind, seed_idx, radius=30.0):
    settings = bpy.context.scene.rigo_brace
    obj = _import_scan(path)
    me = obj.data
    seed = seed_idx if seed_idx < len(me.vertices) else len(me.vertices) // 2
    bpy.context.scene.cursor.location = obj.matrix_world @ me.vertices[seed].co
    settings.region_radius = radius
    settings.region_magnitude = amount
    settings.region_kind = kind
    settings.region_falloff = "SMOOTH"
    bpy.ops.rigo.region_add_circle()
    region = obj.rigo_regions[obj.rigo_region_index]
    weights = _group_weights(obj, region.surface_mask)
    before, before_n, before_fn = _snapshot(obj)
    _pre_dihedral(tag, obj, set(weights))
    _commit_active_region(obj)
    sign = -1.0 if kind == "PRESSURE" else 1.0
    m = _measure(tag, obj, before, before_n, before_fn, weights, amount, sign)
    return obj, region, m


def _case_ctrl(tag, path, amount, seed_idx, smoothed_normals):
    obj = _import_scan(path)
    me = obj.data
    seed = seed_idx if seed_idx < len(me.vertices) else len(me.vertices) // 2
    weights = _geodesic_weights(me, seed, 0.030)
    before, before_n, before_fn = _snapshot(obj)
    _pre_dihedral(tag, obj, set(weights))
    if smoothed_normals:
        _smoothed_normal_displace(obj, weights, amount, -1.0)
    else:
        _apply_displace(obj, weights, amount, -1.0)
    m = _measure(tag, obj, before, before_n, before_fn, weights, amount, -1.0)
    _delete(obj)
    return m


def _save_style_from(obj, label):
    st = bpy.ops.rigo.region_style_save(style_name=label)
    assert st == {"FINISHED"}, f"style save failed: {st}"
    return bpy.context.scene.rigo_brace.region_style


def _case_import(tag, path, style_id, cursor_world, decimate=None,
                 premod=None):
    settings = bpy.context.scene.rigo_brace
    obj = _import_scan(path)
    if decimate is not None:
        mod = obj.modifiers.new("QA_DEC", "DECIMATE")
        mod.ratio = decimate
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=mod.name)
    if premod == "INFLATE":
        mod = obj.modifiers.new("QA_INFLATE", "DISPLACE")
        mod.direction = "NORMAL"
        mod.mid_level = 0.0
        mod.strength = 0.020
    settings.region_style = style_id
    bpy.context.scene.cursor.location = cursor_world
    try:
        st = bpy.ops.rigo.region_style_import()
    except RuntimeError as exc:
        _mark(f"[{tag}] import FAILED: {exc}")
        _delete(obj)
        return None, None
    if st != {"FINISHED"}:
        _mark(f"[{tag}] import returned {st}")
        _delete(obj)
        return None, None
    region = obj.rigo_regions[obj.rigo_region_index]
    weights = _group_weights(obj, region.surface_mask)
    from_lib = importlib.import_module(
        "bl_ext.user_default.rigo_brace.core.region_library"
    )
    entry = from_lib.get_entry(style_id)
    _import_provenance(tag, obj, entry, Vector(cursor_world))
    if premod == "INFLATE":
        # measure where the footprint landed relative to the visible surface
        if weights:
            centroid = Vector()
            for i in weights:
                centroid += obj.data.vertices[i].co
            centroid /= len(weights)
            _mark(
                f"[{tag}] eval-mismatch: cursor={tuple(round(c, 4) for c in cursor_world)} "
                f"raw_mask_centroid={tuple(round(c, 4) for c in centroid)} "
                f"gap={(Vector(cursor_world) - centroid).length * 1000.0:.1f}mm"
            )
        _delete(obj)
        return None, None
    before, before_n, before_fn = _snapshot(obj)
    _pre_dihedral(tag, obj, set(weights))
    _commit_active_region(obj)
    sign = -1.0 if region.kind == "PRESSURE" else 1.0
    m = _measure(tag, obj, before, before_n, before_fn, weights,
                 region.magnitude_mm, sign)
    return obj, m


def _field_compare(tag, m_ref, m_new):
    if m_ref is None or m_new is None:
        return
    keys = set(m_ref["d"]) & set(m_new["d"])
    diffs = [abs(m_ref["d"][k] - m_new["d"][k]) for k in keys]
    inter = len(m_ref["fp"] & m_new["fp"])
    union = len(m_ref["fp"] | m_new["fp"])
    _mark(
        f"[{tag}] field-vs-direct: max|dd|={max(diffs):.2f}mm "
        f"rms={math.sqrt(sum(x * x for x in diffs) / len(diffs)):.3f}mm "
        f"footprint IoU={inter / union:.3f}"
    )


# --------------------------------------------------------------------------- #
def _style_fold_metric(tag, entry):
    """Non-injective 2D projection evidence: close sample pairs, far weights."""
    samples = entry["samples"]
    tree = kdtree.KDTree(len(samples))
    for i, s in enumerate(samples):
        tree.insert((s[0], s[1], 0.0), i)
    tree.balance()
    folds = 0
    maxdw = 0.0
    for i, s in enumerate(samples):
        for _co, j, _d in tree.find_range((s[0], s[1], 0.0), 1.5):
            if j <= i:
                continue
            dw = abs(s[2] - samples[j][2])
            maxdw = max(maxdw, dw)
            if dw > 0.3:
                folds += 1
    _mark(
        f"[{tag}] style-folds: pairs<1.5mm |dw|>0.3: {folds} "
        f"maxdw={maxdw:.3f} n={len(samples)}"
    )


def _build_precommit_entry(scan, region, ident, label):
    """Replicate the save path but from the UNdisplaced geometry."""
    ro = _region_ops_module()
    lib = importlib.import_module(
        "bl_ext.user_default.rigo_brace.core.region_library"
    )
    group = scan.vertex_groups.get(region.surface_mask)
    samples, normal_offsets, weights = ro._style_samples(scan, group)
    spacing = ro._sample_spacing_mm(scan, set(weights))
    entry = {
        "id": ident,
        "label": label,
        "kind": region.kind,
        "magnitude_mm": region.magnitude_mm,
        "falloff": region.falloff_type,
        "samples": samples,
        "sample_radius_mm": max(1.0, spacing * 1.75),
        "normal_tolerance_mm": max(15.0, max(normal_offsets) + spacing * 2.0),
        "requires_orthotist_review": True,
        "schema_version": 1,
    }
    lib.upsert_entry(entry)
    return ident


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    settings = bpy.context.scene.rigo_brace
    region_library = importlib.import_module(
        "bl_ext.user_default.rigo_brace.core.region_library"
    )
    t0 = time.perf_counter()
    state = {}

    def _safe(name, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            _mark(f"[{name}] CASE ERROR={exc!r}\n{traceback.format_exc()}")

    def case_scan_direct_and_styles():
        obj_d15, region_d15, m_d15 = _case_direct_circle(
            "direct_circle_15", _SCAN, 15.0, "PRESSURE", 9000
        )
        _mesh_stats("scan", obj_d15)
        state["cursor_same"] = tuple(bpy.context.scene.cursor.location)
        state["m_d15"] = m_d15
        # NOTE: production save happens AFTER commit — but the region weights
        # still reference the same vertices; build the pre-commit twin from a
        # fresh uncommitted copy for comparison.
        state["style_scan"] = _save_style_from(obj_d15, "QA Qual Scan Style")
        entry = region_library.get_entry(state["style_scan"])
        _mark(
            f"[style_post] samples={len(entry['samples'])} "
            f"sample_radius={entry['sample_radius_mm']:.2f}mm "
            f"normal_tol={entry['normal_tolerance_mm']:.1f}mm "
            f"magnitude={entry['magnitude_mm']}mm"
        )
        _style_fold_metric("style_post", entry)
        _delete(obj_d15)

        # pre-commit twin: add the identical circle, do NOT commit, sample.
        obj2 = _import_scan(_SCAN)
        bpy.context.scene.cursor.location = state["cursor_same"]
        settings.region_radius = 30.0
        settings.region_magnitude = 15.0
        settings.region_kind = "PRESSURE"
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add_circle()
        region = obj2.rigo_regions[obj2.rigo_region_index]
        state["style_pre"] = _build_precommit_entry(
            obj2, region, "QA_QUAL_PRE", "QA Qual Pre Style"
        )
        entry_pre = region_library.get_entry(state["style_pre"])
        _mark(
            f"[style_pre] samples={len(entry_pre['samples'])} "
            f"sample_radius={entry_pre['sample_radius_mm']:.2f}mm "
            f"normal_tol={entry_pre['normal_tolerance_mm']:.1f}mm"
        )
        _style_fold_metric("style_pre", entry_pre)
        _delete(obj2)

    def case_import_post_vs_pre():
        obj_i, m_post = _case_import(
            "import_postsave", _SCAN, state["style_scan"], state["cursor_same"]
        )
        _field_compare("import_postsave", state.get("m_d15"), m_post)
        if obj_i:
            _delete(obj_i)
        obj_i, m_pre = _case_import(
            "import_presave", _SCAN, state["style_pre"], state["cursor_same"]
        )
        _field_compare("import_presave", state.get("m_d15"), m_pre)
        if obj_i:
            _delete(obj_i)

    def case_patient():
        objp = _import_scan(_PATIENT)
        _mesh_stats("patient", objp)
        mep = objp.data
        xs = [v.co.x for v in mep.vertices]
        ys = [v.co.y for v in mep.vertices]
        zs = [v.co.z for v in mep.vertices]
        cx, cz = (min(xs) + max(xs)) * 0.5, (min(zs) + max(zs)) * 0.5
        state["back_idx"] = _nearest_vertex(mep, Vector((cx, min(ys), cz)))
        state["front_idx"] = _nearest_vertex(mep, Vector((cx, max(ys), cz)))
        _mark(
            f"[patient] back_idx={state['back_idx']} front_idx={state['front_idx']}"
        )
        _delete(objp)

        objp, _r, _m = _case_direct_circle(
            "patient_back_direct", _PATIENT, 15.0, "PRESSURE", state["back_idx"]
        )
        state["patient_back_cursor"] = tuple(bpy.context.scene.cursor.location)
        state["style_patient"] = _save_style_from(objp, "QA Qual Patient Style")
        _style_fold_metric(
            "style_patient", region_library.get_entry(state["style_patient"])
        )
        _delete(objp)

        objp, _r, _m = _case_direct_circle(
            "patient_front_direct", _PATIENT, 15.0, "PRESSURE",
            state["front_idx"]
        )
        state["patient_front_cursor"] = tuple(bpy.context.scene.cursor.location)
        _delete(objp)

        # cross-scan import (style authored on Brace Sample)
        obj_i, _m = _case_import(
            "patient_import_cross", _PATIENT, state["style_scan"],
            state["patient_back_cursor"]
        )
        if obj_i:
            _delete(obj_i)
        # same-scan import at a different location (front = concave belly)
        obj_i, _m = _case_import(
            "patient_import_front", _PATIENT, state["style_patient"],
            state["patient_front_cursor"]
        )
        if obj_i:
            _delete(obj_i)

    def case_flat():
        g_src = _make_grid("QA_GRID_SRC", 0.3, 100, 0.3, 1)  # 3 mm spacing
        _mesh_stats("flat_src", g_src)
        seed = _nearest_vertex(g_src.data, Vector((0, 0, 0)))
        bpy.context.scene.cursor.location = g_src.data.vertices[seed].co.copy()
        settings.region_radius = 30.0
        settings.region_magnitude = 15.0
        settings.region_kind = "PRESSURE"
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add_circle()
        region = g_src.rigo_regions[g_src.rigo_region_index]
        weights = _group_weights(g_src, region.surface_mask)
        before, before_n, before_fn = _snapshot(g_src)
        bpy.ops.rigo.region_apply()
        _measure("flat_direct_15", g_src, before, before_n, before_fn,
                 weights, 15.0, -1.0)
        state["style_flat"] = _save_style_from(g_src, "QA Qual Flat Style")
        _style_fold_metric(
            "style_flat", region_library.get_entry(state["style_flat"])
        )
        _delete(g_src)

        for tag, divs, jseed in (
            ("flat_import_dense", 150, 2),   # 2 mm target
            ("flat_import_same", 100, 3),    # 3 mm target, different jitter
            ("flat_import_coarse", 50, 4),   # 6 mm target
        ):
            g_t = _make_grid(f"QA_GRID_{tag}", 0.3, divs, 0.3, jseed)
            settings.region_style = state["style_flat"]
            bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)
            try:
                st = bpy.ops.rigo.region_style_import()
            except RuntimeError as exc:
                _mark(f"[{tag}] import FAILED: {exc}")
                _delete(g_t)
                continue
            if st != {"FINISHED"}:
                _mark(f"[{tag}] import returned {st}")
                _delete(g_t)
                continue
            entry_f = region_library.get_entry(state["style_flat"])
            _import_provenance(tag, g_t, entry_f, Vector((0.0, 0.0, 0.0)))
            region = g_t.rigo_regions[g_t.rigo_region_index]
            weights = _group_weights(g_t, region.surface_mask)
            before, before_n, before_fn = _snapshot(g_t)
            bpy.ops.rigo.region_apply()
            _measure(tag, g_t, before, before_n, before_fn, weights,
                     region.magnitude_mm, -1.0)
            _delete(g_t)

    try:
        _mark("phase=start v2")
        _safe("scan_styles", case_scan_direct_and_styles)
        _safe("post_vs_pre", case_import_post_vs_pre)
        _safe("patient", case_patient)
        _safe("flat", case_flat)
        _mark(f"DONE in {time.perf_counter() - t0:.1f}s")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        lib = importlib.import_module(
            "bl_ext.user_default.rigo_brace.core.region_library"
        )
        for e in list(lib.load_library(force=True)):
            if e.get("label") in _STYLE_LABELS:
                lib.delete_entry(e["id"])
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
