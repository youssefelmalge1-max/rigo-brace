"""#53 — where do the weld and fan pipelines first diverge inside a commit?

Hooks every topology-editing call the refinement makes (_link_safe_collapse,
bmesh.ops.beautify_fill, bmesh.ops.rotate_edges, bmesh.ops.subdivide_edges,
bmesh.ops.triangulate) and records, per call, a fingerprint of the bmesh
BEFORE and AFTER (hash of the sorted oriented faces by vertex index) plus the
call's arguments as vertex-index keys.  Runs the chain once per arm
(RIGO_ARMS=old,new) on the same scan/seed and reports the first event whose
record differs — and whether its INPUT already differed (a Python-side
decision diverged earlier) or only its OUTPUT (that op is order-sensitive).

GUI Blender only; writes refinetracedbg_result.txt.
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
OUT = os.path.join(ROOT, "refinetracedbg_result.txt")
ARMS = os.environ.get("RIGO_ARMS", "old,new").split(",")
DUMP_AT = int(os.environ.get("RIGO_DUMP_AT", "-1"))
DUMP_VERTS = [int(x) for x in os.environ.get("RIGO_DUMP_VERTS", "").split(",") if x]
N_ORIG = 44574
AMOUNT_MM = 15.0
FEATHER_MM = 10.0
PATCH_R = 0.045
TRIES = {"n": 0}
LOG = []
EVENTS = []


def _log(msg):
    LOG.append(str(msg))
    print("[trace]", msg)


def _old_link_safe_collapse(bm, v, n):
    if not (v.is_valid and n.is_valid):
        return False
    nbrs_v = {e.other_vert(v) for e in v.link_edges}
    nbrs_n = {e.other_vert(n) for e in n.link_edges}
    if len(nbrs_v & nbrs_n) != 2:
        return False
    bmesh.ops.weld_verts(bm, targetmap={v: n})
    return True


def _fp(bm):
    faces = []
    for f in bm.faces:
        cyc = [v.index for v in f.verts]
        k = cyc.index(min(cyc))
        faces.append(tuple(cyc[k:] + cyc[:k]))
    faces.sort()
    return hash(tuple(faces)), len(faces), len(bm.verts)


def _ekey(e):
    a, b = e.verts[0].index, e.verts[1].index
    return (a, b) if a < b else (b, a)


def _dump(bm, tag):
    bm.verts.ensure_lookup_table()
    for vi in DUMP_VERTS:
        if vi >= len(bm.verts):
            _log(f"  [{tag}] v{vi}: out of table ({len(bm.verts)})")
            continue
        v = bm.verts[vi]
        faces = []
        for f in v.link_faces:
            els = sorted((e.calc_length(), tuple(sorted(x.index for x in e.verts))) for e in f.edges)
            longest = els[-1][0]
            ratio = 2.0 * f.calc_area() / longest if longest > 0 else -1
            faces.append((tuple(sorted(x.index for x in f.verts)), round(ratio * 1000, 4), [(round(l * 1000, 4), k) for l, k in els]))
        _log(f"  [{tag}] v{vi} idx={v.index} valid={v.is_valid} new={v.index >= N_ORIG} "
             f"co={tuple(round(c, 6) for c in v.co)} manifold={v.is_manifold} boundary={v.is_boundary} "
             f"valence={len(v.link_edges)} faces={faces}")


_ANCHORS = [
    ("        new_set = {v for v in all_new if v.is_valid}\n",
     "        _TRACE(('new_set', h_target, sorted(v.index for v in new_set)))\n"),
    ("        cap_faces.sort(key=_fkey)\n",
     "        _TRACE(('cap_faces', [_fkey(f) for f in cap_faces]))\n"),
    ("            unique.sort(key=_ekey)\n",
     "            _TRACE(('cap_edges', [_ekey(e) for e in unique]))\n"),
    ("            any_collapsed = False\n            for fk, f in purge_faces:\n",
     "            _TRACE(('purge_faces', [fk for fk, _f in purge_faces]))\n"
     "            any_collapsed = False\n            for fk, f in purge_faces:\n"),
    # Inject BEFORE this one (the anchor ends mid-statement).
    ("                done = False\n                for _length, e in sorted(\n",
     "                _TRACE(('purge_try', _fkey(f), round(2.0 * f.calc_area() / longest * 1e6), round(h_target * 1e6)))\n"
     "                done = False\n                for _length, e in sorted(\n"),
]


def _traced_refine(region_ops):
    """Exec a copy of region_ops with trace lines injected after the anchors;
    return the instrumented _refine_footprint bound to that namespace."""
    import types
    src = open(region_ops.__file__, encoding="utf-8").read()
    for anchor, inject in _ANCHORS:
        assert src.count(anchor) == 1, (anchor, src.count(anchor))
        # Entries whose inject already contains the anchor are replacements.
        src = src.replace(anchor, inject if anchor in inject else anchor + inject)
    mod = types.ModuleType("region_ops_traced")
    mod.__dict__.update({k: v for k, v in region_ops.__dict__.items()
                         if k.startswith("__")})
    mod.__dict__["_TRACE"] = lambda rec: EVENTS.append(("trace",) + tuple(rec) + (None, None, None))
    exec(compile(src, region_ops.__file__, "exec"), mod.__dict__)
    return mod


def _install_hooks(region_ops, impl):
    region_ops._link_safe_collapse = impl
    real_collapse = impl

    def collapse_hook(bm, v, n):
        arg = (v.index, n.index)
        if len(EVENTS) == DUMP_AT:
            _dump(bm, f"collapse-entry {arg}")
        before = _fp(bm)
        result = real_collapse(bm, v, n)
        EVENTS.append(("collapse", arg, result, before, _fp(bm)))
        return result

    region_ops._link_safe_collapse = collapse_hook
    traced = _traced_refine(region_ops)
    traced._link_safe_collapse = collapse_hook
    region_ops._refine_footprint = traced._refine_footprint

    def op_hook(name, real):
        def hook(bm, **kw):
            arg = None
            if "edges" in kw:
                arg = [_ekey(e) for e in kw["edges"]]
            elif "faces" in kw:
                arg = [tuple(sorted(v.index for v in f.verts)) for f in kw["faces"]]
            if len(EVENTS) == DUMP_AT:
                _dump(bm, f"{name}-entry {str(arg)[:60]}")
            before = _fp(bm)
            result = real(bm, **kw)
            EVENTS.append((name, arg, None, before, _fp(bm)))
            return result
        return hook

    return {
        name: op_hook(name, getattr(bmesh.ops, name))
        for name in ("beautify_fill", "rotate_edges", "subdivide_edges",
                     "triangulate")
    }


def _arm(settings, shade_smooth_scan):
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
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
    return result, region.refined_added


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
        impls = {"old": _old_link_safe_collapse,
                 "new": region_ops._link_safe_collapse}
        real_ops = {n: getattr(bmesh.ops, n) for n in
                    ("beautify_fill", "rotate_edges", "subdivide_edges",
                     "triangulate")}
        traces = []
        for arm in ARMS:
            EVENTS.clear()
            hooks = _install_hooks(region_ops, impls[arm])
            for name, hook in hooks.items():
                setattr(bmesh.ops, name, hook)
            try:
                result, added = _arm(settings, shade_smooth_scan)
            finally:
                for name, real in real_ops.items():
                    setattr(bmesh.ops, name, real)
            _log(f"arm {arm}: {result} refined_added={added} events={len(EVENTS)}")
            traces.append(list(EVENTS))
        a, b = traces
        n = min(len(a), len(b))
        first = None
        for i in range(n):
            if a[i] != b[i]:
                first = i
                break
        if first is None:
            _log(f"no differing event in {n} common events; lengths {len(a)} vs {len(b)}")
        else:
            ea, eb = a[first], b[first]
            _log(f"FIRST DIFFERENCE at event {first}: {ea[0]} vs {eb[0]}")
            _log(f"  same_kind={ea[0] == eb[0]} same_args={ea[1] == eb[1]} "
                 f"same_result={ea[2] == eb[2]} same_before={ea[3] == eb[3]} "
                 f"same_after={ea[4] == eb[4]}")
            _log(f"  A: {ea[0]} args={str(ea[1])[:200]} res={ea[2]} before={ea[3]} after={ea[4]}")
            _log(f"  B: {eb[0]} args={str(eb[1])[:200]} res={eb[2]} before={eb[3]} after={eb[4]}")
            # context: the few events before
            for j in range(max(0, first - 3), first):
                _log(f"  prior {j}: {a[j][0]} args={str(a[j][1])[:80]} res={a[j][2]} same={a[j] == b[j]}")
    except Exception as error:  # noqa: BLE001
        _log(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(LOG) + "\n")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
