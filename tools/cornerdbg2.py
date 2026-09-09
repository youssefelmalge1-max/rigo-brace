"""#54 Task 3 probe 2: which refinement step creates the non-manifold edges?

Wraps bmesh.ops.subdivide_edges / triangulate / rotate_edges and
region_ops._link_safe_collapse with local manifold checks, then runs
_refine_footprint directly on the B x4 fixture (ROUNDED 4/3 f10 A15 by
default; RIGO_FALLOFF / RIGO_TOP / RIGO_BOTTOM / RIGO_FEATHER override).
Writes cornerdbg2_result.txt.  GUI only.
"""

import os
import sys
import time
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import B_SCAN  # noqa: E402

_OUT = r"C:\Projects\Blender Add-on Braces\cornerdbg2_result.txt"
_TRIES = {"n": 0}
_log = []
FALLOFF = os.environ.get("RIGO_FALLOFF", "ROUNDED")
TOP = float(os.environ.get("RIGO_TOP", "4"))
BOTTOM = float(os.environ.get("RIGO_BOTTOM", "3"))
FEATHER = float(os.environ.get("RIGO_FEATHER", "10"))
FRAC_Z = float(os.environ.get("RIGO_Z", "0.45"))
STATE = {"nonman": 0, "collapses": 0, "bad_collapses": 0, "rotations": 0}


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _paint_circle(obj, frac_z, radius=0.045):
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
        (lo.x + hi.x) * 0.5, lo.y + 0.10 * (hi.y - lo.y), lo.z + frac_z * (hi.z - lo.z),
    )))
    centre = me.vertices[seed].co.copy()
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(me)
    for f in bm.faces:
        if (f.calc_center_median() - centre).length < radius:
            f.select = True
    bmesh.update_edit_mesh(me)


def _count_nonman(bm):
    return sum(1 for e in bm.edges if not e.is_manifold)


def _needles(bm, faces=None, tag=""):
    import math
    out = []
    for f in (faces if faces is not None else bm.faces):
        if not f.is_valid or len(f.verts) != 3:
            continue
        try:
            amin = min(math.degrees(l.calc_angle()) for l in f.loops)
        except ValueError:
            amin = 0.0
        if amin < 3.0:
            out.append((round(amin, 2), tuple(v.index for v in f.verts)))
    if out and tag:
        _mark(f"    needles after {tag}: {len(out)} e.g. {out[:4]}")
    return out


def _install(ro):
    orig_sub = bmesh.ops.subdivide_edges
    orig_tri = bmesh.ops.triangulate
    orig_rot = bmesh.ops.rotate_edges
    orig_col = ro._link_safe_collapse

    def sub(bm, **kw):
        _needles(bm, None, "previous round")
        out = orig_sub(bm, **kw)
        n = _count_nonman(bm)
        _mark(f"  subdivide_edges edges={len(kw.get('edges', ()))} -> nonman={n} verts={len(bm.verts)}")
        STATE["nonman"] = n
        return out

    def tri(bm, **kw):
        faces_in = kw.get("faces", ())
        shapes = {}
        for f in faces_in:
            shapes[tuple(v.index for v in f.verts)] = len(f.verts)
        out = orig_tri(bm, **kw)
        n = _count_nonman(bm)
        _mark(f"  triangulate faces={len(faces_in)} sizes={sorted(set(shapes.values()))} -> nonman={n}")
        if n > STATE["nonman"]:
            shown = 0
            for e in bm.edges:
                if e.is_manifold or shown >= 6:
                    continue
                shown += 1
                a, b = e.verts
                faces = [tuple(v.index for v in f.verts) for f in e.link_faces]
                owners = [k for k in shapes if a.index in k and b.index in k]
                _mark(f"    NONMAN edge ({a.index},{b.index}) len={e.calc_length() * 1000:.3f}mm "
                      f"faces={len(faces)} {faces} | input ngons holding both: {owners}")
        STATE["nonman"] = n
        return out

    def rot(bm, **kw):
        edges = kw.get("edges", ())
        before = [(e.verts[0].index, e.verts[1].index) for e in edges]
        pre_faces = {f for e in edges for f in e.link_faces}
        pre_needles = len(_needles(bm, pre_faces))
        out = orig_rot(bm, **kw)
        STATE["rotations"] += len(edges)
        post_faces = [f for e in out.get("edges", ()) if e.is_valid for f in e.link_faces]
        post_needles = _needles(bm, post_faces)
        if len(post_needles) > pre_needles:
            _mark(f"    rotate_edges made needles: {pre_needles} -> {len(post_needles)} {post_needles[:3]} (edges {before[:3]})")
        bad = 0
        for e in out.get("edges", ()):
            if not e.is_valid:
                continue
            for f in e.link_faces:
                for fe in f.edges:
                    if not fe.is_manifold:
                        bad += 1
        if bad:
            _mark(f"  rotate_edges n={len(edges)} -> local nonman edges {bad} (pairs {before[:4]})")
        return out

    def col(bm, v, n):
        vi, ni = v.index, n.index
        nv = len(v.link_edges) if v.is_valid else -1
        pre_needles = len(_needles(bm, list(v.link_faces) + list(n.link_faces))) if v.is_valid and n.is_valid else 0
        out = orig_col(bm, v, n)
        if out:
            STATE["collapses"] += 1
            if n.is_valid:
                post_needles = _needles(bm, list(n.link_faces))
                if len(post_needles) > pre_needles:
                    _mark(f"    collapse {vi}->{ni} made needles: {post_needles[:3]}")
            if n.is_valid:
                bad = [e for e in n.link_edges if not e.is_manifold]
                bad2 = [fe for f in n.link_faces for fe in f.edges if not fe.is_manifold]
                if bad or bad2:
                    STATE["bad_collapses"] += 1
                    if STATE["bad_collapses"] <= 12:
                        _mark(f"  COLLAPSE v={vi}(valence {nv}) -> n={ni}: "
                              f"nonman at n {len(bad)} / ring {len(set(bad2))}; "
                              f"n valence {len(n.link_edges)} boundary={n.is_boundary}")
        return out

    bmesh.ops.subdivide_edges = sub
    bmesh.ops.triangulate = tri
    bmesh.ops.rotate_edges = rot
    ro._link_safe_collapse = col


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        import importlib
        ro = importlib.import_module(
            "bl_ext.user_default.rigo_brace.operators.region_ops"
        )
        from bl_ext.user_default.rigo_brace.operators.scan_ops import (  # noqa
            shade_smooth_scan,
        )
        settings = bpy.context.scene.rigo_brace
        bpy.ops.wm.stl_import(filepath=B_SCAN)
        obj = bpy.context.active_object
        settings.scan_object = obj
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.subdivide(number_cuts=1, smoothness=1.0)
        bpy.ops.object.mode_set(mode="OBJECT")
        shade_smooth_scan(obj.data)

        _paint_circle(obj, FRAC_Z)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 15.0
        settings.region_feather = FEATHER
        settings.region_falloff = FALLOFF
        settings.region_top_radius = TOP
        settings.region_bottom_radius = BOTTOM
        bpy.ops.rigo.region_add()
        bpy.ops.object.mode_set(mode="OBJECT")
        region = obj.rigo_regions[obj.rigo_region_index]
        gi = obj.vertex_groups.get(region.surface_mask).index
        field = ro._authored_rim_field(obj.data, gi, region)
        _mark(f"region {FALLOFF} {TOP}/{BOTTOM} f{FEATHER} edge_mm={region.edge_mm:.2f} field={'yes' if field else 'None'}")

        _install(ro)
        copy = obj.data.copy()
        t0 = time.perf_counter()
        added, h = ro._refine_footprint(copy, gi, -0.015, field=field)
        bm = bmesh.new()
        bm.from_mesh(copy)
        final = _count_nonman(bm)
        _needles(bm, None, "refinement (pre-displacement)")
        bm.free()
        _mark(f"refine: added={added} h_target={h:.3f}mm final nonman={final} "
              f"collapses={STATE['collapses']} bad_collapses={STATE['bad_collapses']} "
              f"rotations={STATE['rotations']} ({time.perf_counter() - t0:.1f}s)")
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
