"""#53 — in-situ differential replay of every collapse in one real commit.

Wraps region_ops._link_safe_collapse: for each call that passes the link
condition, COPY the bmesh, run the OLD mesh-wide weld on the copy and the
shipped implementation on the original, then compare the two meshes as
faces-over-vertex-ordinals (both copies keep vertex order; kills never
reorder) and deform weights.  Reports the first divergence with the local
situation (valence, n-gons left, refusal), so a pipeline difference can be
attributed to the primitive or to something else.

GUI Blender only; writes collapsereplaydbg_result.txt.
"""

import os
import sys
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import A_SCAN  # noqa: E402

ROOT = r"C:\Projects\Blender Add-on Braces"
OUT = os.path.join(ROOT, "collapsereplaydbg_result.txt")
AMOUNT_MM = 15.0
FEATHER_MM = 10.0
PATCH_R = 0.045
TRIES = {"n": 0}
LOG = []
STATS = {"calls": 0, "gated": 0, "compared": 0, "mismatch": 0, "fan": 0,
         "weld_fallback": 0}


def _log(msg):
    LOG.append(str(msg))
    print("[replay]", msg)


def _ordinals(bm):
    return {v: k for k, v in enumerate(bm.verts)}


def _faces(bm, ords):
    out = set()
    for f in bm.faces:
        cyc = [ords[v] for v in f.verts]
        k = cyc.index(min(cyc))
        out.add(tuple(cyc[k:] + cyc[:k]))  # oriented: winding matters
    return out


def _weights(bm, ords):
    layer = bm.verts.layers.deform.active
    if layer is None:
        return {}
    return {ords[v]: dict(v[layer]) for v in bm.verts}


def _wrap(region_ops):
    orig = region_ops._link_safe_collapse
    orig_fan = region_ops._fan_collapse

    def counted_fan(v, n, link):
        ok = orig_fan(v, n, link)
        STATS["fan" if ok else "weld_fallback"] += 1
        return ok

    region_ops._fan_collapse = counted_fan

    def wrapped(bm, v, n):
        STATS["calls"] += 1
        if not (v.is_valid and n.is_valid):
            return orig(bm, v, n)
        nbrs_v = {e.other_vert(v) for e in v.link_edges}
        nbrs_n = {e.other_vert(n) for e in n.link_edges}
        if len(nbrs_v & nbrs_n) != 2:
            return orig(bm, v, n)
        STATS["gated"] += 1
        ords = _ordinals(bm)
        kv, kn = ords[v], ords[n]
        valence = len(nbrs_v)
        tri = all(len(f.verts) == 3 for f in v.link_faces)
        manifold, boundary = v.is_manifold, v.is_boundary
        bm2 = bm.copy()
        bm2.verts.ensure_lookup_table()
        v2, n2 = bm2.verts[kv], bm2.verts[kn]
        bmesh.ops.weld_verts(bm2, targetmap={v2: n2})
        result = orig(bm, v, n)
        # Surviving vertex ordinals: both killed exactly v (ordinal kv).
        ords_a = {}
        for k, vv in enumerate(bm.verts):
            ords_a[vv] = k if k < kv else k + 1
        ords_b = {}
        for k, vv in enumerate(bm2.verts):
            ords_b[vv] = k if k < kv else k + 1
        fa, fb = _faces(bm, ords_a), _faces(bm2, ords_b)
        wa, wb = _weights(bm, ords_a), _weights(bm2, ords_b)
        STATS["compared"] += 1
        if fa != fb or wa != wb:
            STATS["mismatch"] += 1
            if STATS["mismatch"] <= 5:
                ngons = sum(1 for f in n.link_faces if len(f.verts) > 3)
                wdiff = [k for k in wa if wa[k] != wb.get(k)]
                _log(
                    f"MISMATCH #{STATS['mismatch']} call={STATS['calls']} "
                    f"v_ord={kv} n_ord={kn} valence={valence} tri={tri} "
                    f"manifold={manifold} boundary={boundary} "
                    f"len_verts new={len(bm.verts)} old={len(bm2.verts)} "
                    f"faces new={len(fa)} old={len(fb)} "
                    f"only_new={len(fa - fb)} only_old={len(fb - fa)} "
                    f"ngons_at_n={ngons} weight_diffs={len(wdiff)} "
                    f"sample_only_new={sorted(map(sorted, list(fa - fb)[:3]))} "
                    f"sample_only_old={sorted(map(sorted, list(fb - fa)[:3]))}"
                )
        bm2.free()
        return result

    region_ops._link_safe_collapse = wrapped


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 60:
        return 0.25
    try:
        import importlib
        region_ops = importlib.import_module(
            "bl_ext.user_default.rigo_brace.operators.region_ops"
        )
        _wrap(region_ops)
        settings = bpy.context.scene.rigo_brace
        bpy.ops.wm.stl_import(filepath=A_SCAN)
        obj = bpy.context.active_object
        settings.scan_object = obj
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        me = obj.data
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
        bpy.ops.object.mode_set(mode="OBJECT")
        result = bpy.ops.rigo.region_apply()
        region = obj.rigo_regions[obj.rigo_region_index]
        _log(f"commit {result} refined_added={region.refined_added} "
             f"verts={len(obj.data.vertices)}")
        _log(str(STATS))
        _log(f"PRIMITIVE_EQUIVALENT={STATS['mismatch'] == 0}")
    except Exception as error:  # noqa: BLE001
        _log(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(LOG) + "\n")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
