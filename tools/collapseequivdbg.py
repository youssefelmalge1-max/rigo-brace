"""#53 — is the local fan collapse identical to the mesh-wide weld it replaced?

Runs the orthotist's chain twice on the SAME scan, seed, amount and feather
(import -> units -> optional subdivide -> paint circle -> live region ->
commit): arm A with a verbatim copy of the OLD ``_link_safe_collapse`` body
(bmesh.ops.weld_verts every time) monkey-patched in, arm B with the shipped
local implementation.  Compares the committed meshes as GEOMETRY, not indices
(weld and fan both create new faces, so index order is meaningless):

  * vertex count and the multiset of vertex coordinates (rounded 1e-9 m)
  * the set of faces as frozensets of vertex coordinates
  * non-manifold edge count, refined_added, wall dihedral spectrum
  * commit wall time per arm

RIGO_SUBDIV=0|1 subdivides the scan first (Edit-mode smooth subdivide), same
as tools/subdivshot.py.  Writes collapseequivdbg_L<n>_result.txt with
EQUIVALENT=True/False.  GUI Blender only.
"""

import math
import os
import sys
import time
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import A_SCAN  # noqa: E402

LEVELS = int(os.environ.get("RIGO_SUBDIV", "0"))
# Which implementation each arm runs: "old,new" (default), "old,old" or
# "new,new" are the determinism controls, "new,old" the order control.
ARMS = os.environ.get("RIGO_ARMS", "old,new").split(",")
# Patch centre as fractions of the bounding box (x, y, z); several seeds
# tell noise from a systematic wall difference.
SEED = tuple(float(s) for s in os.environ.get("RIGO_SEED", "0.5,0.10,0.45").split(","))
ROOT = r"C:\Projects\Blender Add-on Braces"
OUT = os.path.join(
    ROOT,
    f"collapseequivdbg_L{LEVELS}_{'_'.join(ARMS)}_"
    f"{'_'.join(f'{s:.2f}' for s in SEED)}_result.txt",
)
AMOUNT_MM = 15.0
FEATHER_MM = 10.0
PATCH_R = 0.045
TRIES = {"n": 0}
LOG = []


def _log(msg):
    LOG.append(str(msg))
    print("[collapseequiv]", msg)


def _old_link_safe_collapse(bm, v, n):
    """VERBATIM pre-#53 body (region_ops.py at ed5a052)."""
    if not (v.is_valid and n.is_valid):
        return False
    nbrs_v = {e.other_vert(v) for e in v.link_edges}
    nbrs_n = {e.other_vert(n) for e in n.link_edges}
    if len(nbrs_v & nbrs_n) != 2:
        return False
    bmesh.ops.weld_verts(bm, targetmap={v: n})
    return True


def _spectrum(values):
    if not values:
        return "n=0"
    values = sorted(values)

    def p(q):
        return values[min(len(values) - 1, int(q * len(values)))]

    return (
        f"n={len(values)} p50={p(0.5):.3f} p95={p(0.95):.3f} "
        f"max={values[-1]:.3f} >30deg={sum(1 for x in values if x > 30.0)}"
    )


def _wall(me, weights):
    bm = bmesh.new()
    bm.from_mesh(me)
    angles = []
    for e in bm.edges:
        a, b = e.verts[0].index, e.verts[1].index
        wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
        if not (0.05 < wa < 0.95 and 0.05 < wb < 0.95):
            continue
        if len(e.link_faces) != 2:
            continue
        try:
            angles.append(abs(math.degrees(e.calc_face_angle_signed())))
        except ValueError:
            angles.append(180.0)
    bm.free()
    return _spectrum(angles)


def _key(co):
    return (round(co.x, 9), round(co.y, 9), round(co.z, 9))


def _snapshot(obj, region, group):
    me = obj.data
    weights = {}
    for v in me.vertices:
        for g in v.groups:
            if g.group == group.index:
                weights[v.index] = g.weight
                break
    # Both arms keep the same vertex order (kills never reorder), so faces
    # compare by oriented index tuples and positions by max deviation —
    # summation order over disk cycles differs between the primitives and
    # leaves ~1e-16 relative float noise that coordinate keys would flag.
    faces = set()
    for p in me.polygons:
        cyc = list(p.vertices)
        k = cyc.index(min(cyc))
        faces.add(tuple(cyc[k:] + cyc[:k]))
    coords = [0.0] * (3 * len(me.vertices))
    me.vertices.foreach_get("co", coords)
    counts = [0] * len(me.edges)
    for loop in me.loops:
        counts[loop.edge_index] += 1
    return {
        "verts": len(me.vertices),
        "faces": len(me.polygons),
        "coords": coords,
        "face_set": faces,
        "nonmanifold": sum(1 for c in counts if c != 2),
        "refined_added": region.refined_added,
        "wall": _wall(me, weights),
    }


def _arm(settings, region_ops, shade_smooth_scan, tag):
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
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
        lo.x + SEED[0] * (hi.x - lo.x),
        lo.y + SEED[1] * (hi.y - lo.y),
        lo.z + SEED[2] * (hi.z - lo.z),
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
    t0 = time.perf_counter()
    result = bpy.ops.rigo.region_apply()
    dt = time.perf_counter() - t0
    snap = _snapshot(obj, region, group)
    _log(
        f"{tag}: commit {result} {dt:.2f}s verts={snap['verts']} "
        f"faces={snap['faces']} refined_added={snap['refined_added']} "
        f"nonmanifold={snap['nonmanifold']} wall {snap['wall']}"
    )
    snap["time"] = dt
    return snap


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
        impls = {
            "old": _old_link_safe_collapse,
            "new": region_ops._link_safe_collapse,
        }
        _log(f"arms={ARMS} seed={SEED} levels={LEVELS}")
        region_ops._link_safe_collapse = impls[ARMS[0]]
        old = _arm(settings, region_ops, shade_smooth_scan, f"ARM1 {ARMS[0]}")
        region_ops._link_safe_collapse = impls[ARMS[1]]
        new = _arm(settings, region_ops, shade_smooth_scan, f"ARM2 {ARMS[1]}")
        region_ops._link_safe_collapse = impls["new"]
        if old["verts"] == new["verts"]:
            max_dev = max(abs(a - b) for a, b in zip(old["coords"], new["coords"]))
        else:
            max_dev = float("inf")
        # 1 µm: below the scan's own resolution by three orders; what
        # survives is summation order over disk cycles (measured 3e-7 m).
        same_verts = max_dev < 1e-6
        same_faces = old["face_set"] == new["face_set"]
        only_old = len(old["face_set"] - new["face_set"])
        only_new = len(new["face_set"] - old["face_set"])
        _log(
            f"max_vertex_dev_m={max_dev:.3e} face_set_equal={same_faces} "
            f"faces_only_old={only_old} faces_only_new={only_new}"
        )
        _log(
            f"speedup={old['time'] / max(new['time'], 1e-9):.2f}x "
            f"({old['time']:.2f}s -> {new['time']:.2f}s)"
        )
        equivalent = (
            same_verts and same_faces
            and old["nonmanifold"] == new["nonmanifold"]
            and old["refined_added"] == new["refined_added"]
        )
        _log(f"EQUIVALENT={equivalent}")
    except Exception as error:  # noqa: BLE001
        _log(f"ERROR={error!r}\n{traceback.format_exc()}\nEQUIVALENT=False")
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(LOG) + "\n")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
