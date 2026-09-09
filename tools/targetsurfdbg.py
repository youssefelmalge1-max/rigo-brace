"""#54 — separate the AUTHORED macro shape from LOCAL surface quality.

One Blender process per arm (RIGO_ARM), same scan / paint / amount / camera:

  base        production pipeline
  norefine    production minus adaptive refinement (unrefined commit)
  dir_const   displace along ONE direction (the region's mean normal)
              instead of per-vertex faired normals
  dir_wide    faired normals over a 25 mm radius instead of ~2 edges
  fair_base   fair the BASE surface under the footprint first (umbrella
              Laplacian, strength = weight, 10 passes), then production
  fall_<K>    falloff profile K in {LINEAR, SHARP, QUINTIC, EASEIN, EASEOUT}
  combo       fair_base + dir_const (RIGO_FEATHER sets the width)

Metrics, every arm, on the committed mesh (originals keep their indices):
  macro   realized depth of plateau originals along the mean direction (mm),
          |displacement| / (amount*w) ratio, max movement of w=0 originals
  local   normal-projected umbrella Laplacian |mean(ring)-v|.n in mm, PRE
          (scan itself) and POST, plateau (w>0.95) and wall (0.05<w<0.95);
          spikes = post > 0.5 mm and > 2x pre; dihedral spectra; 2-ring
          normal residual (what smooth shading shows)
Outputs: targetsurfdbg_<scan>_L<n>_<arm>_a<amount>_f<feather>.txt + _solid.png
"""

import math
import os
import statistics
import sys
import time
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import A_SCAN, B_SCAN  # noqa: E402

ARM = os.environ.get("RIGO_ARM", "base")
LEVELS = int(os.environ.get("RIGO_SUBDIV", "1"))
SCAN = os.environ.get("RIGO_SCAN", "B")
AMOUNT_MM = float(os.environ.get("RIGO_AMOUNT", "15"))
FEATHER_MM = float(os.environ.get("RIGO_FEATHER", "10"))
ROOT = r"C:\Projects\Blender Add-on Braces"
TAG = f"targetsurfdbg_{SCAN}_L{LEVELS}_{ARM}_a{AMOUNT_MM:g}_f{FEATHER_MM:g}"
PATCH_R = 0.045
TRIES = {"n": 0}
LOG = []


def _log(msg):
    LOG.append(str(msg))
    print("[targetsurf]", msg)


def _spec(values):
    if not values:
        return "n=0"
    v = sorted(values)

    def p(q):
        return v[min(len(v) - 1, int(q * len(v)))]

    return (f"n={len(v)} p50={p(0.5):.3f} p95={p(0.95):.3f} max={v[-1]:.3f}")


# ------------------------------- falloffs ---------------------------------- #
def _quintic(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _easein(t):   # quick near the outline, gentle toward the plateau
    return 1.0 - (1.0 - t) ** 3


def _easeout(t):  # gentle near the outline, quick toward the plateau
    return t ** 3


_CURVES = {"QUINTIC": _quintic, "EASEIN": _easein, "EASEOUT": _easeout}


def _patch_falloff(region_ops, curve):
    orig_f = region_ops._falloff

    def f(t, kind):
        if kind == "SMOOTH":
            return curve(min(max(t, 0.0), 1.0))
        return orig_f(t, kind)

    def inv(y, kind):
        if kind != "SMOOTH":
            return region_ops_inv(y, kind)
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if curve(mid) < y:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    region_ops_inv = region_ops._inv_falloff
    region_ops._falloff = f
    region_ops._inv_falloff = inv


# ------------------------------- arms -------------------------------------- #
def _install_arm(region_ops, settings):
    settings.region_falloff = "SMOOTH"
    if ARM.startswith("round_"):
        # #54 Task 2: the native ROUNDED profile, arm name round_<top>_<bottom>
        top, bottom = ARM[6:].split("_")
        settings.region_falloff = "ROUNDED"
        settings.region_top_radius = float(top)
        settings.region_bottom_radius = float(bottom)
    if ARM.startswith("fall_"):
        kind = ARM[5:]
        if kind in ("LINEAR", "SHARP"):
            settings.region_falloff = kind
        else:
            _patch_falloff(region_ops, _CURVES[kind])
    if ARM == "norefine":
        region_ops._refine_footprint = lambda *a, **k: (0, 0.0)
    if ARM in ("dir_const", "combo"):
        orig = region_ops._faired_normals

        def const(me, weights, mean_edge):
            faired, adjacency = orig(me, weights, mean_edge)
            acc = Vector()
            for i, w in weights.items():
                if w > 0.95:
                    acc += me.vertices[i].normal
            acc.normalize()
            return {i: acc.copy() for i in faired}, adjacency

        region_ops._faired_normals = const
    if ARM == "dir_wide":
        orig = region_ops._faired_normals
        region_ops._faired_normals = (
            lambda me, weights, mean_edge: orig(me, weights, 0.0125)
        )


def _fair_base(obj, group_index, passes=10):
    """Umbrella Laplacian on the footprint, strength = authored weight, so the
    outline (w=0) and everything outside are untouched by construction."""
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    deform = bm.verts.layers.deform.active
    w = {v.index: v[deform].get(group_index, 0.0) for v in bm.verts}
    member = [v for v in bm.verts if w[v.index] > 0.0]
    for _ in range(passes):
        moves = []
        for v in member:
            nb = [e.other_vert(v) for e in v.link_edges]
            if not nb:
                continue
            mean = Vector()
            for n in nb:
                mean += n.co
            mean /= len(nb)
            moves.append((v, v.co.lerp(mean, 0.5 * w[v.index])))
        for v, co in moves:
            v.co = co
    bm.to_mesh(me)
    bm.free()
    me.update()


# ------------------------------- metrics ----------------------------------- #
def _adjacency(me):
    adj = [[] for _ in range(len(me.vertices))]
    for e in me.edges:
        a, b = e.vertices
        adj[a].append(b)
        adj[b].append(a)
    return adj


def _roughness(me, adj, indices):
    """Normal-projected umbrella Laplacian magnitude, mm, per vertex."""
    out = {}
    verts = me.vertices
    for i in indices:
        nb = adj[i]
        if len(nb) < 3:
            continue
        mean = Vector()
        for j in nb:
            mean += verts[j].co
        mean /= len(nb)
        out[i] = abs((mean - verts[i].co).dot(verts[i].normal)) * 1000.0
    return out


def _dihedrals(me, weights, lo, hi):
    bm = bmesh.new()
    bm.from_mesh(me)
    out = []
    for e in bm.edges:
        a, b = e.verts[0].index, e.verts[1].index
        wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
        if not (lo < wa <= hi and lo < wb <= hi):
            continue
        if len(e.link_faces) != 2:
            continue
        try:
            out.append(abs(math.degrees(e.calc_face_angle_signed())))
        except ValueError:
            out.append(180.0)
    bm.free()
    return out


def _shade_residual(me, adj, indices):
    out = []
    verts = me.vertices
    for i in indices:
        ring = set()
        for j in adj[i]:
            ring.add(j)
            ring.update(adj[j])
        ring.discard(i)
        if len(ring) < 4:
            continue
        mean = Vector()
        for j in ring:
            mean += verts[j].normal
        if mean.length < 1e-9:
            continue
        mean.normalize()
        d = max(-1.0, min(1.0, verts[i].normal.normalized().dot(mean)))
        out.append(math.degrees(math.acos(d)))
    return out


def _weights(me, group_index):
    w = {}
    for v in me.vertices:
        for g in v.groups:
            if g.group == group_index:
                w[v.index] = g.weight
                break
    return w


def _shoot(centre_world, normal_world):
    area = next(a for a in bpy.context.screen.areas if a.type == "VIEW_3D")
    space = area.spaces.active
    region = next(r for r in area.regions if r.type == "WINDOW")
    look = (-normal_world).normalized()
    up = Vector((0.0, 0.0, 1.0))
    if abs(look.dot(up)) > 0.9:
        up = Vector((0.0, 1.0, 0.0))
    look = (look + up * 0.35).normalized()
    quat = look.to_track_quat("-Z", "Y")
    sh = space.shading
    sh.type = "SOLID"
    sh.light = "STUDIO"
    sh.color_type = "SINGLE"
    sh.single_color = (0.80, 0.83, 0.88)
    sh.show_xray = False
    space.overlay.show_overlays = False
    with bpy.context.temp_override(area=area, region=region):
        rv3d = space.region_3d
        rv3d.view_perspective = "PERSP"
        rv3d.view_rotation = quat
        rv3d.view_location = centre_world
        rv3d.view_distance = 0.16
        rv3d.update()
        bpy.context.scene.render.resolution_x = 1400
        bpy.context.scene.render.resolution_y = 1000
        bpy.context.scene.render.resolution_percentage = 100
        bpy.context.scene.render.filepath = os.path.join(ROOT, f"{TAG}_solid.png")
        bpy.ops.render.opengl(write_still=True)


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
        _install_arm(region_ops, settings)
        _log(f"arm={ARM} scan={SCAN} L{LEVELS} amount={AMOUNT_MM} feather={FEATHER_MM}")

        bpy.ops.wm.stl_import(filepath=B_SCAN if SCAN == "B" else A_SCAN)
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
            (lo.x + hi.x) * 0.5, lo.y + 0.10 * (hi.y - lo.y), lo.z + 0.45 * (hi.z - lo.z),
        )))
        centre_local = me.vertices[seed].co.copy()
        centre_world = mw @ centre_local
        normal_world = (mw.to_3x3() @ me.vertices[seed].normal).normalized()

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
        bpy.ops.rigo.region_add()
        region = obj.rigo_regions[obj.rigo_region_index]
        group = obj.vertex_groups.get(region.surface_mask)
        bpy.ops.object.mode_set(mode="OBJECT")

        if ARM in ("fair_base", "combo"):
            _fair_base(obj, group.index)
            # Rebuild the authored field on the faired base (selection is
            # still in the mesh), exactly as the orthotist's Update does.
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.rigo.region_update()
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            group = obj.vertex_groups.get(region.surface_mask)

        me = obj.data
        n_orig = len(me.vertices)
        w_pre = _weights(me, group.index)
        adj_pre = _adjacency(me)
        plateau_pre = [i for i, w in w_pre.items() if w > 0.95]
        wall_pre = [i for i, w in w_pre.items() if 0.05 < w < 0.95]
        rough_pre = _roughness(me, adj_pre, plateau_pre + wall_pre)
        pre_co = [v.co.copy() for v in me.vertices]
        mean_dir = Vector()
        for i in plateau_pre:
            mean_dir += me.vertices[i].normal
        mean_dir.normalize()
        _log(f"pre: verts={n_orig} plateau={len(plateau_pre)} wall={len(wall_pre)} "
             f"rough_plateau_pre {_spec([rough_pre[i] for i in plateau_pre if i in rough_pre])} "
             f"rough_wall_pre {_spec([rough_pre[i] for i in wall_pre if i in rough_pre])}")

        t0 = time.perf_counter()
        result = bpy.ops.rigo.region_apply()
        dt = time.perf_counter() - t0
        me = obj.data
        w_post = _weights(me, group.index)
        adj = _adjacency(me)
        _log(f"commit {result} {dt:.2f}s refined_added={region.refined_added} "
             f"verts={len(me.vertices)}")

        # ---- macro fidelity (originals keep their indices) ----
        depth = []
        ratio = []
        outside = 0.0
        for i in range(n_orig):
            w = w_pre.get(i, 0.0)
            d = me.vertices[i].co - pre_co[i]
            if w > 0.95:
                depth.append(-d.dot(mean_dir) * 1000.0)
            if w > 0.0:
                ratio.append(d.length / (AMOUNT_MM * 0.001 * w))
            else:
                outside = max(outside, d.length * 1000.0)
        _log(f"macro: depth_along_mean_dir_mm p50={statistics.median(depth):.2f} "
             f"min={min(depth):.2f} max={max(depth):.2f} (authored {AMOUNT_MM}) | "
             f"|disp|/(amount*w) mean={statistics.mean(ratio):.4f} "
             f"min={min(ratio):.3f} max={max(ratio):.3f} | outside_moved_mm={outside:.4f}")

        # ---- local quality ----
        plateau = [i for i, w in w_post.items() if w > 0.95]
        wall = [i for i, w in w_post.items() if 0.05 < w < 0.95]
        rough = _roughness(me, adj, plateau + wall)
        rp = [rough[i] for i in plateau if i in rough]
        rw = [rough[i] for i in wall if i in rough]
        spikes_p = sum(1 for i in plateau if i in rough and i < n_orig and i in rough_pre
                       and rough[i] > 0.5 and rough[i] > 2.0 * rough_pre[i])
        spikes_w = sum(1 for i in wall if i in rough and i < n_orig and i in rough_pre
                       and rough[i] > 0.5 and rough[i] > 2.0 * rough_pre[i])
        _log(f"local: rough_plateau_post {_spec(rp)} spikes={spikes_p} | "
             f"rough_wall_post {_spec(rw)} spikes={spikes_w}")
        # Split the "plateau" into the flat CORE (w >= 0.999) and the top
        # SHOULDER (0.95 < w < 0.999): the profile's upper corner lives in
        # the shoulder, the core is a rigid translation when w == 1.
        core = [i for i in plateau if w_post[i] >= 0.999]
        shoulder = [i for i in plateau if w_post[i] < 0.999]
        rc = [rough[i] for i in core if i in rough]
        rs = [rough[i] for i in shoulder if i in rough]
        rc_pre = [rough_pre[i] for i in core if i in rough_pre and i < n_orig]
        _log(f"split: core_pre {_spec(rc_pre)} core_post {_spec(rc)} "
             f"core_spikes={sum(1 for i in core if i in rough and i in rough_pre and rough[i] > 0.5 and rough[i] > 2.0 * rough_pre[i])} | "
             f"shoulder_post {_spec(rs)} "
             f"shoulder_spikes={sum(1 for i in shoulder if i in rough and i in rough_pre and rough[i] > 0.5 and rough[i] > 2.0 * rough_pre[i])} | "
             f"dihedral core {_spec(_dihedrals(me, w_post, 0.999, 1.0))} "
             f"shoulder {_spec(_dihedrals(me, w_post, 0.95, 0.999))}")
        _log(f"dihedral plateau {_spec(_dihedrals(me, w_post, 0.95, 1.0))} | "
             f"wall {_spec(_dihedrals(me, w_post, 0.05, 0.95))}")
        _log(f"shade_residual_deg plateau {_spec(_shade_residual(me, adj, plateau))} | "
             f"wall {_spec(_shade_residual(me, adj, wall))}")
        for other in bpy.context.scene.objects:
            other.hide_set(other is not obj)
        _shoot(centre_world, normal_world)
    except Exception as error:  # noqa: BLE001
        _log(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(os.path.join(ROOT, f"{TAG}.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(LOG) + "\n")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
