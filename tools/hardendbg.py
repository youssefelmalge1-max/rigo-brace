"""#48 hardening probe — reproduce/falsify the council backlog findings.

Evidence-only diagnostic (no gates, no production changes).  One case per
council finding that needs geometric reproduction:

  mirror     (#2) snapshot bypass + metadata loss on RIGO_OT_region_mirror
  editupdate (#3) Edit Selection -> Update Preview destroys imported fields
  oppwall    (#4) deep press pierces the opposite body wall undetected
  adjfold    (#5) adjacent-face fold-over evades flip + selfx predicates
  chartfold  (#6) tangent chart non-injective at large radius on curvature
  horseshoe  (#7) geodesic trim deletes the far lobe of a C-shaped pad

Writes hardendbg_result.txt.  GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools\hardendbg.py
"""

import importlib
import json
import math
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree
from mathutils.bvhtree import BVHTree

_OUT = r"C:\Projects\Blender Add-on Braces\hardendbg_result.txt"
_SCAN = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []
_QA_LABELS = ("QA HD Mirror Src", "QA HD Mirror", "QA HD EditUpd", "QA HS Style")


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


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


def _own_mesh(name, verts, faces):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    settings = bpy.context.scene.rigo_brace
    settings.scan_object = obj
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    return obj


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


def _global_selfx(me, member):
    """Independent oracle: WHOLE-mesh face crossings touching the footprint."""
    verts = [v.co for v in me.vertices]
    polys = [tuple(p.vertices) for p in me.polygons]
    tree = BVHTree.FromPolygons(verts, polys, all_triangles=True)
    hits = []
    for a, b in tree.overlap(tree):
        if a >= b or set(polys[a]) & set(polys[b]):
            continue
        touches_fp = any(vi in member for vi in polys[a] + polys[b])
        one_outside = not all(vi in member for vi in polys[a]) or not all(
            vi in member for vi in polys[b]
        )
        hits.append((a, b, touches_fp, one_outside))
    return hits


def _flat_grid(name, size_m, divisions):
    bm = bmesh.new()
    bmesh.ops.create_grid(
        bm, x_segments=divisions, y_segments=divisions, size=size_m * 0.5
    )
    bmesh.ops.triangulate(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    settings = bpy.context.scene.rigo_brace
    settings.scan_object = obj
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    return obj


# --------------------------------------------------------------------------- #
def _case_mirror(ro, lib, settings):
    obj = _import_scan(_SCAN)
    me = obj.data
    bpy.context.scene.cursor.location = obj.matrix_world @ me.vertices[9000].co
    settings.region_radius = 30.0
    settings.region_magnitude = 8.0
    settings.region_kind = "PRESSURE"
    settings.region_falloff = "SMOOTH"
    bpy.ops.rigo.region_add_circle()
    src = obj.rigo_regions[obj.rigo_region_index]
    src_mask = src.surface_mask
    src.anatomical_label = "THORACIC_APEX"
    bpy.ops.rigo.region_apply()
    st = bpy.ops.rigo.region_style_save(style_name="QA HD Mirror Src")
    src_entry = lib.get_entry(settings.region_style)
    _mark(
        f"[mirror] source: committed+saved st={st} "
        f"snapshot_present={obj.get('rigo_style_src_' + src_mask) is not None} "
        f"entry_keys={sorted(src_entry.keys())}"
    )
    _mark(
        f"[mirror] metadata loss in entry: anatomical_label stored="
        f"{'anatomical_label' in src_entry} opposing/pairing stored="
        f"{'opposing_region' in src_entry or 'pair' in str(sorted(src_entry.keys()))}"
    )

    obj.rigo_region_index = 0
    bpy.ops.rigo.region_mirror()
    mir = obj.rigo_regions[obj.rigo_region_index]
    mir_mask = mir.surface_mask
    snap_missing = obj.get("rigo_style_src_" + mir_mask) is None
    _mark(
        f"[mirror] mirrored region '{mir.name}' kind={mir.kind} "
        f"anatomical_label={mir.anatomical_label} opposing={mir.opposing_region} "
        f"SNAPSHOT_MISSING={snap_missing}"
    )
    # Voronoi nearest-vertex transfer quality of the mirrored mask
    w = _group_weights(obj, mir_mask)
    adj = {}
    for e in me.edges:
        a, b = e.vertices
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    holes = 0
    for i in list(w) + [n for i in w for n in adj.get(i, ())]:
        if w.get(i, 0.0) < 0.1 and sum(
            1 for n in adj.get(i, ()) if w.get(n, 0.0) > 0.5
        ) >= 3:
            holes += 1
    _mark(f"[mirror] mirrored mask: verts={len(w)} weight_field_holes={holes}")

    bpy.ops.rigo.region_apply()  # commit the mirrored (EXPANSION) region
    st = bpy.ops.rigo.region_style_save(style_name="QA HD Mirror")
    mir_entry = lib.get_entry(settings.region_style)
    # RC3 check: the fallback samples the CURRENT (displaced) surface; the
    # bulge shows up as a large max normal offset -> normal_tolerance_mm.
    _mark(
        f"[mirror] mirror-save st={st} fell_back_to_displaced={snap_missing} "
        f"src_normal_tol={src_entry['normal_tolerance_mm']:.1f}mm "
        f"mir_normal_tol={mir_entry['normal_tolerance_mm']:.1f}mm "
        f"(bulge magnitude was 8mm)"
    )
    _delete(obj)


def _case_editupdate(ro, lib, settings):
    # Author a style from a circle region (radial smoothstep field, r=30).
    obj = _import_scan(_SCAN)
    me = obj.data
    bpy.context.scene.cursor.location = obj.matrix_world @ me.vertices[9000].co
    settings.region_radius = 30.0
    settings.region_magnitude = 8.0
    settings.region_kind = "PRESSURE"
    settings.region_falloff = "SMOOTH"
    bpy.ops.rigo.region_add_circle()
    bpy.ops.rigo.region_apply()
    bpy.ops.rigo.region_style_save(style_name="QA HD EditUpd")
    style_id = settings.region_style
    _delete(obj)

    obj = _import_scan(_SCAN)
    me = obj.data
    settings.region_style = style_id
    bpy.context.scene.cursor.location = obj.matrix_world @ me.vertices[9000].co
    bpy.ops.rigo.region_style_import()
    region = obj.rigo_regions[obj.rigo_region_index]
    w0 = _group_weights(obj, region.surface_mask)
    fall0 = region.falloff_type
    snap0 = obj.get("rigo_style_src_" + region.surface_mask)

    # The user opens the footprint for editing and immediately updates —
    # WITHOUT changing the selection and WITHOUT touching panel settings
    # deliberately (they hold whatever the panel last had).
    settings.region_feather = 10.0
    settings.region_falloff = "SHARP"
    bpy.ops.rigo.region_edit()
    bpy.ops.rigo.region_update()
    w1 = _group_weights(obj, region.surface_mask)
    fall1 = region.falloff_type
    snap1 = obj.get("rigo_style_src_" + region.surface_mask)

    union = set(w0) | set(w1)
    diffs = [abs(w0.get(i, 0.0) - w1.get(i, 0.0)) for i in union]
    rms = math.sqrt(sum(d * d for d in diffs) / len(diffs))
    changed = sum(1 for d in diffs if d > 0.05)
    lost = sum(1 for i in w0 if w0[i] > 0.3 and w1.get(i, 0.0) < 0.05)
    _mark(
        f"[editupdate] verts before={len(w0)} after={len(w1)} "
        f"weight_rms_diff={rms:.3f} changed(>0.05)={changed} "
        f"core_lost(w0>0.3->w1<0.05)={lost}"
    )
    _mark(
        f"[editupdate] falloff_type {fall0} -> {fall1}  "
        f"snapshot_replaced={snap0 != snap1}"
    )
    _delete(obj)


def _case_oppwall(ro, settings):
    # Squashed sphere: 24 mm thick disc, 180 mm wide (an M&M) — a stand-in
    # for any thin body region (rib prominence over lung window, arm, edge).
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=96, v_segments=64, radius=1.0)
    for v in bm.verts:
        v.co.x *= 0.09
        v.co.y *= 0.012
        v.co.z *= 0.09
    bmesh.ops.triangulate(bm, faces=bm.faces)
    me = bpy.data.meshes.new("QA_OPPWALL")
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new("QA_OPPWALL", me)
    bpy.context.scene.collection.objects.link(obj)
    settings.scan_object = obj
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    me = obj.data
    top = max(me.vertices, key=lambda v: v.co.y - v.co.xz.length * 0.001)
    bpy.context.scene.cursor.location = obj.matrix_world @ top.co
    settings.region_radius = 25.0
    settings.region_magnitude = 30.0  # wall-to-wall is only 24 mm
    settings.region_kind = "PRESSURE"
    settings.region_falloff = "SMOOTH"
    bpy.ops.rigo.region_add_circle()
    region = obj.rigo_regions[obj.rigo_region_index]
    weights = _group_weights(obj, region.surface_mask)
    member = {i for i, w in weights.items() if w >= 1e-6}
    thickness0 = 24.0
    st = bpy.ops.rigo.region_apply()
    fp_selfx = ro._footprint_self_intersections(me, member)
    global_hits = _global_selfx(me, member)
    cross_wall = [h for h in global_hits if h[2] and h[3]]
    min_y = min(me.vertices[i].co.y for i in member) * 1000.0
    _mark(
        f"[oppwall] thickness={thickness0}mm amount=30mm commit={st} "
        f"footprint_selfx={len(fp_selfx)} global_crossings={len(global_hits)} "
        f"footprint-vs-otherwall_crossings={len(cross_wall)} "
        f"deepest_point_y={min_y:.1f}mm (bottom wall at -12.0mm => "
        f"pierced {max(0.0, -12.0 - min_y):.1f}mm past it)"
    )
    _delete(obj)


def _case_adjfold(ro):
    # Smallest fixture: two triangles sharing edge AB at a steep crease.
    # Folding the crease closed rotates face 2 by ~70 deg (< 90: flip test
    # blind) onto/through face 1 (shared edge: selfx pair excluded).
    A = (0.0, 0.0, 0.0)
    B = (0.01, 0.0, 0.0)
    C = (0.005, 0.010, 0.0)
    for tag, D0, D1 in (
        # flat-ish crease, large rotation: flip test SHOULD catch these two
        ("foldover_flat", (0.005, -0.003, 0.009), (0.005, 0.003, 0.0005)),
        ("crossing_flat", (0.005, -0.003, 0.009), (0.005, 0.003, -0.0005)),
        # pre-creased wall (85 deg up, barely overhanging): folding it flat
        # onto face 1 is only an 80 deg rotation -> flip test stays blind
        ("foldover_creased", (0.005, 0.00087, 0.00996),
         (0.005, 0.00995, 0.00087)),
    ):
        obj = _own_mesh(f"QA_ADJ_{tag}", [A, B, C, D0], [(0, 1, 2), (1, 0, 3)])
        me = obj.data
        pre = {p.index: p.normal.copy() for p in me.polygons}
        me.vertices[3].co = Vector(D1)
        me.update()
        member = {0, 1, 2, 3}
        flips = [
            p.index for p in me.polygons
            if p.normal.dot(pre[p.index]) <= 1e-9
        ]
        degen = [p.index for p in me.polygons if p.area < 1e-12]
        selfx = ro._footprint_self_intersections(me, member)
        rot = math.degrees(
            me.polygons[1].normal.angle(pre[1])
        )
        # Fold detector candidate: adjacent-face normals turned antiparallel
        # (edge dihedral collapsed) where they were not before.
        fold_dot_pre = pre[0].dot(pre[1])
        fold_dot_post = me.polygons[0].normal.dot(me.polygons[1].normal)
        # Independent oracle: winding sign of each face projected on the
        # SHARED pre-commit plane normal (fold-over flips the projected sign).
        n_ref = (pre[0] + pre[1]).normalized() if (pre[0] + pre[1]).length > 1e-9 else pre[0]
        signs = []
        for p in me.polygons:
            vs = [me.vertices[i].co for i in p.vertices]
            signs.append((vs[1] - vs[0]).cross(vs[2] - vs[0]).dot(n_ref))
        _mark(
            f"[adjfold.{tag}] face2_rotation={rot:.0f}deg "
            f"flip_detected={bool(flips)} degen={bool(degen)} "
            f"selfx_detected={len(selfx) > 0} "
            f"adjacent_normal_dot pre={fold_dot_pre:.2f} post={fold_dot_post:.2f} "
            f"ORACLE projected_winding_signs={['+' if s > 0 else '-' for s in signs]} "
            f"(defect present, production predicates see: "
            f"{'NOTHING' if not flips and not degen and not selfx else 'something'})"
        )
        _delete(obj)


def _case_chartfold(ro, settings):
    # Cylinder R=60mm: geodesic 140mm reaches 133 deg of arc; the tangent
    # chart u = R*sin(theta) folds every point past 90 deg back inward.
    R = 0.06
    n_theta, n_z, dz = 126, 100, 0.003
    verts, faces = [], []
    for k in range(n_z):
        z = (k - n_z * 0.5) * dz
        for t in range(n_theta):
            a = 2.0 * math.pi * t / n_theta
            verts.append((R * math.cos(a), R * math.sin(a), z))
    for k in range(n_z - 1):
        for t in range(n_theta):
            a0 = k * n_theta + t
            a1 = k * n_theta + (t + 1) % n_theta
            b0 = a0 + n_theta
            b1 = a1 + n_theta
            faces.append((a0, a1, b1))
            faces.append((a0, b1, b0))
    obj = _own_mesh("QA_CHART", verts, faces)
    me = obj.data
    anchor_world = obj.matrix_world @ Vector((R, 0.0, 0.0))
    bpy.context.scene.cursor.location = anchor_world
    settings.region_radius = 140.0
    settings.region_magnitude = 3.0
    settings.region_kind = "PRESSURE"
    settings.region_falloff = "SMOOTH"
    bpy.ops.rigo.region_add_circle()
    region = obj.rigo_regions[obj.rigo_region_index]
    weights = _group_weights(obj, region.surface_mask)

    target, normal = ro._target_surface(obj, anchor_world)
    side, up, outward = ro._surface_frame(normal)
    matrix = obj.matrix_world
    chart = {}
    for i in weights:
        rel = matrix @ me.vertices[i].co - target
        chart[i] = (rel.dot(side) * 1000.0, rel.dot(up) * 1000.0)
    tree = kdtree.KDTree(len(chart))
    idx_list = list(chart)
    for n, i in enumerate(idx_list):
        u, v = chart[i]
        tree.insert((u, v, 0.0), n)
    tree.balance()
    collisions = 0
    example = None
    for n, i in enumerate(idx_list):
        u, v = chart[i]
        for _co, m, dist in tree.find_range((u, v, 0.0), 1.5):
            j = idx_list[m]
            if j <= i:
                continue
            d3 = (me.vertices[i].co - me.vertices[j].co).length * 1000.0
            if d3 > 30.0:
                collisions += 1
                if example is None:
                    example = (i, j, dist, d3, weights[i], weights[j])
    _mark(
        f"[chartfold] R=60mm circle_radius=140mm member_verts={len(weights)} "
        f"chart_collision_pairs(<1.5mm apart in 2D, >30mm apart in 3D)={collisions}"
    )
    if example:
        i, j, d2, d3, wi, wj = example
        _mark(
            f"[chartfold] example: v{i} and v{j} chart_gap={d2:.2f}mm "
            f"surface_gap={d3:.0f}mm weights={wi:.2f}/{wj:.2f} "
            f"-> one 2D cell must store two incompatible surface weights"
        )
    _delete(obj)


def _case_horseshoe(ro, lib, settings):
    # C-shaped pad on a flat grid: mean radius 60 mm, width 30 mm, gap at
    # angle 0 (+/-40 deg).  Authored footprint arc length ~250 mm.
    obj = _flat_grid("QA_HS_SRC", 0.3, 100)
    me = obj.data
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(me)
    for f in bm.faces:
        c = f.calc_center_median()
        r = math.hypot(c.x, c.y) * 1000.0
        ang = abs(math.degrees(math.atan2(c.y, c.x)))
        f.select = 45.0 <= r <= 75.0 and ang > 40.0
    bmesh.update_edit_mesh(me)
    settings.region_kind = "PRESSURE"
    settings.region_magnitude = 5.0
    settings.region_feather = 10.0
    settings.region_falloff = "SMOOTH"
    bpy.ops.rigo.region_add()
    region = obj.rigo_regions[obj.rigo_region_index]
    w_auth = _group_weights(obj, region.surface_mask)
    auth_eff = {i for i, w in w_auth.items() if w > 0.05}
    bpy.ops.rigo.region_apply()
    bpy.ops.rigo.region_style_save(style_name="QA HS Style")
    style_id = settings.region_style
    _delete(obj)

    obj = _flat_grid("QA_HS_DST", 0.3, 100)  # identical grid -> same indices
    me = obj.data
    settings.region_style = style_id
    bpy.context.scene.cursor.location = Vector((-0.06, 0.0, 0.0))
    st = bpy.ops.rigo.region_style_import()
    region = obj.rigo_regions[obj.rigo_region_index]
    w_imp = _group_weights(obj, region.surface_mask)
    imp_eff = {i for i, w in w_imp.items() if w > 0.05}
    iou = len(auth_eff & imp_eff) / len(auth_eff | imp_eff)
    lost = auth_eff - imp_eff

    def _angspan(indices):
        angs = sorted(
            math.degrees(math.atan2(me.vertices[i].co.y, me.vertices[i].co.x))
            for i in indices
        )
        return (angs[0], angs[-1]) if angs else (0.0, 0.0)

    _mark(
        f"[horseshoe] import={st} authored_eff={len(auth_eff)} "
        f"imported_eff={len(imp_eff)} IoU={iou:.3f} "
        f"lost_verts={len(lost)} ({100.0 * len(lost) / max(1, len(auth_eff)):.0f}% "
        f"of the authored pad)"
    )
    _mark(
        f"[horseshoe] authored_angle_span={_angspan(auth_eff)} "
        f"imported_angle_span={_angspan(imp_eff)} (gap authored at +/-40deg)"
    )
    _delete(obj)


# --------------------------------------------------------------------------- #
def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    ro = importlib.import_module(
        "bl_ext.user_default.rigo_brace.operators.region_ops"
    )
    lib = importlib.import_module(
        "bl_ext.user_default.rigo_brace.core.region_library"
    )
    settings = bpy.context.scene.rigo_brace

    def _safe(name, fn, *args):
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            _mark(f"[{name}] CASE ERROR={exc!r}\n{traceback.format_exc()}")

    try:
        _mark("phase=start")
        _safe("mirror", _case_mirror, ro, lib, settings)
        _safe("editupdate", _case_editupdate, ro, lib, settings)
        _safe("oppwall", _case_oppwall, ro, settings)
        _safe("adjfold", _case_adjfold, ro)
        _safe("chartfold", _case_chartfold, ro, settings)
        _safe("horseshoe", _case_horseshoe, ro, lib, settings)
        _mark("DONE=True")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        for e in list(lib.load_library(force=True)):
            if e.get("label") in _QA_LABELS:
                lib.delete_entry(e["id"])
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
