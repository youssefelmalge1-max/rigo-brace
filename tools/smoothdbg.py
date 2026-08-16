"""#49f: what does SMOOTHING do to a committed correction?

Stage 1 walks the orthotist's chain once (import -> paint -> live region ->
commit) and measures the committed surface.  Stage 2 then runs every candidate
smoothing operator on IDENTICAL committed geometry (positions are saved and
restored between arms), so the arms differ only in the operator:

  area          production 'Smooth Area' = bpy.ops.mesh.vertices_smooth on the
                SELECTED vertices: uniform Laplacian, HARD CLAMP at the
                selection border, tangential motion included
  brush         sculpt-mode Smooth brush replica: uniform Laplacian scaled by
                the brush's radial falloff (the cut-off is the brush edge)
  lap_w         uniform Laplacian FEATHERED by the region's own falloff weight
  taubin_w      Taubin lambda/mu (non-shrinking) feathered by the weight
  taubin_wn     same, normal component only (no tangential drift)
  hc_w          Vollmer HC-Laplacian feathered by the weight

Metrics per arm:
  wall      dihedral spectrum of the transition band (what the eye reads)
  ridges    CONVEX dihedrals >10 deg inside a pressed (concave) wall = the
            literal speed bumps
  depth     realized correction depth vs the authored amount (median AND min:
            a smoothing pass that eats the correction unevenly is a clinical
            defect, not a polish)
  ring      dihedral spectrum of edges CROSSING the operator's boundary - the
            signature of an operator that stops abruptly
  step      how far a boundary vertex moved while its neighbour outside the
            operator's reach stayed put (the physical height of that crease)
  outside   how far vertices the correction never weighted moved off the
            pre-smooth surface (the region's 'nothing outside moves' promise)

Evidence only - writes smoothdbg_result.txt, changes no product code.
"""

import importlib
import math
import os
import sys
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import A_SCAN  # noqa: E402

_OUT = r"C:\Projects\Blender Add-on Braces\smoothdbg_result.txt"
_TRIES = {"n": 0}
_log = []

AMOUNT_MM = 20.0
FEATHER_MM = 15.0
PATCH_R = 0.059
FACTOR = 0.5
PASSES = 5


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _spectrum(values):
    if not values:
        return "n=0"
    values = sorted(values)
    return (
        f"n={len(values)} mean={sum(values)/len(values):.1f} "
        f"p95={values[int(len(values)*0.95)]:.1f} max={values[-1]:.1f} "
        f">30deg={sum(1 for a in values if a > 30.0)}"
    )


def _wall(me, weights):
    bm = bmesh.new()
    bm.from_mesh(me)
    angles = []
    ridges = 0
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
            ridges += 1
    bm.free()
    return f"wall {_spectrum(angles)} ridges={ridges}"


def _ring_and_step(me, before, moved):
    """Dihedral spectrum AND physical height of the crease at the operator's
    boundary: edges with one endpoint the operator could move and one it
    could not."""
    bm = bmesh.new()
    bm.from_mesh(me)
    angles = []
    step = 0.0
    for e in bm.edges:
        a, b = e.verts[0].index, e.verts[1].index
        if (a in moved) == (b in moved):
            continue
        inner = a if a in moved else b
        if inner < len(before):
            step = max(step, (me.vertices[inner].co - before[inner]).length)
        if len(e.link_faces) != 2:
            continue
        try:
            angles.append(abs(math.degrees(e.calc_face_angle_signed())))
        except ValueError:
            angles.append(180.0)
    bm.free()
    return f"ring {_spectrum(angles)} step={step*1000.0:.2f}mm"


def _depth(me, base_bvh, weights):
    core = []
    for i, w in weights.items():
        if w < 0.95 or i >= len(me.vertices):
            continue
        loc, _n, _idx, _d = base_bvh.find_nearest(me.vertices[i].co)
        if loc is not None:
            core.append((me.vertices[i].co - loc).length * 1000.0)
    if not core:
        return "depth=n/a"
    core.sort()
    med = core[len(core) // 2]
    return (
        f"depth med={med:.2f} min={core[0]:.2f} max={core[-1]:.2f}mm "
        f"({100.0*med/AMOUNT_MM:.0f}% of authored, worst point "
        f"{100.0*core[0]/AMOUNT_MM:.0f}%)"
    )


def _drift_outside(me, before, weights, moved):
    normal_max = tangent_max = 0.0
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    for i in moved:
        if i >= len(before):
            continue
        delta = me.vertices[i].co - before[i]
        if delta.length < 1e-9:
            continue
        n = bm.verts[i].normal
        normal_max = max(normal_max, abs(delta.dot(n)))
        tangent_max = max(tangent_max, (delta - n * delta.dot(n)).length)
    bm.free()
    outside = 0.0
    for i in range(min(len(before), len(me.vertices))):
        if weights.get(i, 0.0) > 0.0:
            continue
        outside = max(outside, (me.vertices[i].co - before[i]).length)
    return (
        f"moved normal_max={normal_max*1000.0:.2f}mm "
        f"tangential_max={tangent_max*1000.0:.2f}mm | "
        f"outside_moved={outside*1000.0:.3f}mm"
    )


# --------------------------------------------------------------------------- #
# smoothing operators under test
# --------------------------------------------------------------------------- #
def _neighbour_means(bm, indices):
    out = {}
    for i in indices:
        v = bm.verts[i]
        neighbours = [e.other_vert(v) for e in v.link_edges]
        if not neighbours:
            continue
        mean = Vector()
        for n in neighbours:
            mean += n.co
        out[i] = mean / len(neighbours)
    return out


def _weighted_smooth(obj, strength, passes, mode, lam=0.5):
    """mode: 'lap' | 'taubin' | 'taubin_n' | 'hc'  — all feathered by
    ``strength`` (per-vertex), so the operator has no hard edge anywhere."""
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    field = [i for i in strength if strength[i] > 0.0]
    mu = -lam / (1.0 - 0.1 * lam)
    original = {i: bm.verts[i].co.copy() for i in field}
    for _ in range(passes):
        steps = (lam, mu) if mode.startswith("taubin") else (lam,)
        for step in steps:
            if mode == "taubin_n":
                bm.normal_update()
            means = _neighbour_means(bm, field)
            moves = []
            for i, mean in means.items():
                v = bm.verts[i]
                delta = mean - v.co
                if mode == "taubin_n":
                    n = v.normal
                    delta = n * delta.dot(n)
                moves.append((v, v.co + delta * (step * strength[i])))
            for v, co in moves:
                v.co = co
        if mode == "hc":
            # Vollmer's HC correction: push back toward the original by the
            # mean of the accumulated displacement — removes shrinkage
            # without the mu inflation step.
            diff = {i: bm.verts[i].co - original[i] for i in field}
            means = _neighbour_means(bm, field)
            moves = []
            for i in field:
                v = bm.verts[i]
                neighbours = [e.other_vert(v) for e in v.link_edges]
                acc = Vector()
                count = 0
                for n in neighbours:
                    if n.index in diff:
                        acc += diff[n.index]
                        count += 1
                if not count:
                    continue
                correction = diff[i] * 0.5 + (acc / count) * 0.5
                moves.append((v, v.co - correction * (0.6 * strength[i])))
            for v, co in moves:
                v.co = co
    bm.to_mesh(me)
    bm.free()
    me.update()
    return set(field)


def _brush_smooth(obj, centre, radius, strength, passes):
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    factors = {}
    for v in bm.verts:
        t = (v.co - centre).length / radius
        if t >= 1.0:
            continue
        s = 1.0 - t
        factors[v.index] = strength * (s * s * (3.0 - 2.0 * s))
    for _ in range(passes):
        means = _neighbour_means(bm, list(factors))
        moves = [
            (bm.verts[i], bm.verts[i].co.lerp(mean, factors[i]))
            for i, mean in means.items()
        ]
        for v, co in moves:
            v.co = co
    bm.to_mesh(me)
    bm.free()
    me.update()
    return set(factors)


def _reselect(obj, member):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    n = 0
    for f in bm.faces:
        if all(v.index in member for v in f.verts):
            f.select = True
            n += 1
    bmesh.update_edit_mesh(obj.data)
    return n


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    importlib.import_module(
        "bl_ext.user_default.rigo_brace.operators.region_ops"
    )
    settings = bpy.context.scene.rigo_brace
    try:
        # ---------------- STAGE 1: the chain, once ----------------
        bpy.ops.wm.stl_import(filepath=A_SCAN)
        obj = bpy.context.active_object
        settings.scan_object = obj
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        me = obj.data
        sharp = me.attributes.get("sharp_edge")
        _mark(
            f"STEP 1 import+units: verts={len(me.vertices)} "
            f"flat_faces={sum(1 for p in me.polygons if not p.use_smooth)} "
            f"sharp_edges="
            f"{sum(1 for d in sharp.data if d.value) if sharp else -1}"
        )

        cos = [obj.matrix_world @ v.co for v in me.vertices]
        z_min, z_max = min(c.z for c in cos), max(c.z for c in cos)
        y_min, y_max = min(c.y for c in cos), max(c.y for c in cos)
        x_min, x_max = min(c.x for c in cos), max(c.x for c in cos)
        kd = kdtree.KDTree(len(me.vertices))
        for v in me.vertices:
            kd.insert(obj.matrix_world @ v.co, v.index)
        kd.balance()
        _co, seed, _d = kd.find(Vector((
            (x_min + x_max) * 0.5,
            y_min + 0.10 * (y_max - y_min),
            z_min + 0.45 * (z_max - z_min),
        )))
        centre_local = me.vertices[seed].co.copy()

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(me)
        painted = 0
        for f in bm.faces:
            if (f.calc_center_median() - centre_local).length < PATCH_R:
                f.select = True
                painted += 1
        bmesh.update_edit_mesh(me)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = AMOUNT_MM
        settings.region_feather = FEATHER_MM
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add()
        region = obj.rigo_regions[obj.rigo_region_index]
        group = obj.vertex_groups.get(region.surface_mask)
        bpy.ops.object.mode_set(mode="OBJECT")
        _mark(
            f"STEP 2+3 paint {painted} faces -> live region: "
            f"modifiers={[m.type for m in obj.modifiers]}"
        )

        base = [v.co.copy() for v in me.vertices]
        base_bvh = BVHTree.FromPolygons(
            base, [tuple(p.vertices) for p in me.polygons], all_triangles=True
        )
        bpy.ops.rigo.region_apply()
        me = obj.data
        weights = {}
        for v in me.vertices:
            for g in v.groups:
                if g.group == group.index:
                    weights[v.index] = g.weight
                    break
        member = {i for i, w in weights.items() if w > 0.0}
        _mark(
            f"STEP 4 commit: refined_added={region.refined_added} "
            f"verts={len(me.vertices)} modifiers={[m.type for m in obj.modifiers]}"
        )
        _mark(f"  {_wall(me, weights)}")
        _mark(f"  {_depth(me, base_bvh, weights)}")

        committed = [v.co.copy() for v in me.vertices]
        centre = Vector()
        core = [i for i, w in weights.items() if w > 0.95]
        for i in core:
            centre += me.vertices[i].co
        centre /= max(1, len(core))
        radius = max((me.vertices[i].co - centre).length for i in member) * 1.05

        def restore():
            for i, co in enumerate(committed):
                me.vertices[i].co = co
            me.update()

        # ---------------- STAGE 2: smoothing operators ----------------
        _mark("")
        _mark("STEP 5 - the SAME committed mesh, one smoothing operator each")
        for arm in ("area", "brush", "lap_w", "taubin_w", "taubin_wn", "hc_w"):
            restore()
            if arm == "area":
                n_sel = _reselect(obj, member)
                settings.select_smooth_factor = FACTOR
                settings.select_smooth_iters = PASSES
                bpy.ops.rigo.smooth_selection()
                bpy.ops.object.mode_set(mode="OBJECT")
                moved = set(member)
                note = f"vertices_smooth on {n_sel} selected faces"
            elif arm == "brush":
                moved = _brush_smooth(obj, centre, radius, 0.7, PASSES)
                note = f"brush r={radius*1000:.0f}mm strength=0.7"
            else:
                strength = {i: FACTOR * w for i, w in weights.items() if w > 0}
                mode = {
                    "lap_w": "lap", "taubin_w": "taubin",
                    "taubin_wn": "taubin_n", "hc_w": "hc",
                }[arm]
                moved = _weighted_smooth(obj, strength, PASSES, mode)
                note = f"{mode}, strength = {FACTOR} x falloff weight"
            me = obj.data
            _mark("")
            _mark(f"  [{arm}] {note}")
            _mark(f"    {_wall(me, weights)}")
            _mark(f"    {_depth(me, base_bvh, weights)}")
            _mark(f"    {_ring_and_step(me, committed, moved)}")
            _mark(f"    {_drift_outside(me, committed, weights, moved)}")
        _mark("")
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
