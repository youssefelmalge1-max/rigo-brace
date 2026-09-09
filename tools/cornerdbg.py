"""#54 Task 3 probe: why did the corner-refined commit fall back?

Wraps the commit's internals (refine, non-manifold count, repair, dissolve
plans) with logging and runs one ROUNDED 4/3 f10 A15 commit on the B x4
fixture.  RIGO_FALLOFF / RIGO_TOP / RIGO_BOTTOM / RIGO_FEATHER override.
Writes cornerdbg_result.txt.  GUI only.
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

_OUT = r"C:\Projects\Blender Add-on Braces\cornerdbg_result.txt"
_TRIES = {"n": 0}
_log = []
FALLOFF = os.environ.get("RIGO_FALLOFF", "ROUNDED")
TOP = float(os.environ.get("RIGO_TOP", "4"))
BOTTOM = float(os.environ.get("RIGO_BOTTOM", "3"))
FEATHER = float(os.environ.get("RIGO_FEATHER", "10"))
FRAC_Z = float(os.environ.get("RIGO_Z", "0.45"))


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


def _wrap(ro, name, describe):
    orig = getattr(ro, name)

    def wrapped(*args, **kwargs):
        t0 = time.perf_counter()
        out = orig(*args, **kwargs)
        _mark(f"  {name} -> {describe(args, kwargs, out)} ({time.perf_counter() - t0:.2f}s)")
        return out

    setattr(ro, name, wrapped)


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
        _wrap(ro, "_refine_footprint",
              lambda a, k, out: f"added={out[0]} h_target={out[1] * 1000:.3f}mm "
                                f"verts={len(a[0].vertices)} field={'yes' if k.get('field') else 'None'}")
        _wrap(ro, "_nonmanifold_count", lambda a, k, out: f"{out} (verts={len(a[0].vertices)})")
        _wrap(ro, "_repair_folds",
              lambda a, k, out: f"remaining={out} new_start={k.get('new_start')} sliver_h={k.get('sliver_h')}")
        _wrap(ro, "_sliver_dissolve_plan", lambda a, k, out: f"plan={'None' if out is None else len(out)}")
        _wrap(ro, "_footprint_self_intersections", lambda a, k, out: f"{len(out) if hasattr(out, '__len__') else out}")

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
        _mark(f"region {FALLOFF} top={TOP} bottom={BOTTOM} feather={FEATHER} "
              f"edge_mm={region.edge_mm:.2f} depth={region.depth_mm:.1f} "
              f"readout='{ro.transition_readout(region)[0]}'")

        # Direct refinement on a copy: how many edges want splitting and why.
        field = ro._authored_rim_field(obj.data, gi, region)
        _mark(f"rim_field={'yes' if field else 'None'} "
              f"min_corner={getattr(field, 'min_corner_radius', None)}")
        copy = obj.data.copy()
        t0 = time.perf_counter()
        added, h = ro._refine_footprint(copy, gi, -0.015, field=field)
        _mark(f"direct refine: added={added} h_target={h * 1000:.3f}mm "
              f"nonman {ro._nonmanifold_count(obj.data)} -> {ro._nonmanifold_count(copy)} "
              f"({time.perf_counter() - t0:.1f}s)")
        bpy.data.meshes.remove(copy)

        _mark("commit:")
        t0 = time.perf_counter()
        result = bpy.ops.rigo.region_apply()
        region = obj.rigo_regions[obj.rigo_region_index]
        _mark(f"commit {result} {time.perf_counter() - t0:.1f}s "
              f"refined_added={region.refined_added} note='{region.commit_note}'")
        # Worst shoulder edges (0.95 < w < 0.999) after the commit.
        import math
        me = obj.data
        w = {}
        for v in me.vertices:
            for g in v.groups:
                if g.group == gi:
                    w[v.index] = g.weight
                    break
        n_orig = 179436
        bm = bmesh.new()
        bm.from_mesh(me)
        worst = []
        for e in bm.edges:
            a, b = e.verts
            wa, wb = w.get(a.index, 0.0), w.get(b.index, 0.0)
            if not (0.95 < wa < 0.999 and 0.95 < wb < 0.999) or len(e.link_faces) != 2:
                continue
            try:
                ang = abs(math.degrees(e.calc_face_angle_signed()))
            except ValueError:
                ang = 180.0
            if ang > 40.0:
                worst.append((ang, a.index, b.index, e.calc_length() * 1000.0,
                              wa, wb, [round(f.calc_area() * 1e6, 4) for f in e.link_faces],
                              [len(f.verts) for f in e.link_faces],
                              [round(x, 3) for x in (a.normal.dot(b.normal),)]))
        # Needle census in the footprint (any member vertex): height vs the
        # repair's sliver_h = 0.12 x refined edge.
        needles = []
        for f in bm.faces:
            if not any(v.index in w for v in f.verts):
                continue
            try:
                amin = min(math.degrees(l.calc_angle()) for l in f.loops)
            except ValueError:
                amin = 0.0
            if amin < 3.0:
                longest = max(e.calc_length() for e in f.edges)
                h = 2.0 * f.calc_area() / longest if longest > 0 else 0.0
                needles.append((amin, h * 1000.0, f.calc_area() * 1e6,
                                [(v.index, v.index >= n_orig, round(w.get(v.index, 0.0), 4)) for v in f.verts]))
        needles.sort()
        _mark(f"  needles<3deg in footprint: {len(needles)} (refined_edge={region.refined_edge_mm:.2f}mm -> sliver_h={0.12 * region.refined_edge_mm:.3f}mm)")
        for row in needles[:8]:
            _mark(f"    angle={row[0]:.2f} height={row[1]:.4f}mm area={row[2]:.4f}mm2 verts={row[3]}")
        worst.sort(reverse=True)
        for row in worst[:10]:
            ang, ia, ib, ln, wa, wb, areas, sizes, dots = row
            _mark(f"  SHOULDER dihedral {ang:.1f} edge ({ia}{'n' if ia >= n_orig else ''},"
                  f"{ib}{'n' if ib >= n_orig else ''}) len={ln:.3f}mm w=({wa:.4f},{wb:.4f}) "
                  f"areas_mm2={areas} nrm_dot={dots[0]}")
        bm.free()
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
