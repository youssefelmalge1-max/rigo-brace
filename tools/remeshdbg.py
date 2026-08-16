"""#49h: the remesh path, and smoothing that blends OUT of the paint.

PART 1 — shading after a remesh.  The orthotist reports the corrected area
looks terraced again "after I make it remesh and they gave it a very, very
detailed meshing".  A REMESH modifier hands back a brand-new mesh; #49c
established that FLAT shading alone is the dominant reason a smooth wall reads
as plates.  Counts flat faces and crease marks before and after the remesh.

PART 2 — Smooth Area's reach.  The orthotist's own diagnosis: smoothing works
"within its shape" instead of distributing across the painted area and out
into the rest of the body.  Measures, on a committed 20 mm correction, how far
the influence reaches, whether there is any cliff where it stops, and what it
does to the transition wall.

Evidence only.
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

_OUT = r"C:\Projects\Blender Add-on Braces\remeshdbg_result.txt"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _shading(me, label):
    sharp = me.attributes.get("sharp_edge")
    flat = sum(1 for p in me.polygons if not p.use_smooth)
    return (
        f"{label}: verts={len(me.vertices)} faces={len(me.polygons)} "
        f"flat_faces={flat} ({100.0*flat/max(1,len(me.polygons)):.0f}%) "
        f"crease_marks={sum(1 for d in sharp.data if d.value) if sharp else -1}"
    )


def _fresh(settings):
    bpy.ops.wm.stl_import(filepath=A_SCAN)
    obj = bpy.context.active_object
    settings.scan_object = obj
    settings.scan_units = "mm"
    bpy.ops.rigo.apply_units()
    me = obj.data
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
    return obj, me.vertices[seed].co.copy()


def _paint(obj, centre, radius_mm):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    n = 0
    for f in bm.faces:
        if (f.calc_center_median() - centre).length < radius_mm * 0.001:
            f.select = True
            n += 1
    bmesh.update_edit_mesh(obj.data)
    return n


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
    if not angles:
        return "wall n=0"
    angles.sort()
    return (
        f"wall n={len(angles)} mean={sum(angles)/len(angles):.1f} "
        f"p95={angles[int(len(angles)*0.95)]:.1f} "
        f">30deg={sum(1 for a in angles if a > 30.0)} ridges={ridges}"
    )


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    importlib.import_module(
        "bl_ext.user_default.rigo_brace.operators.select_ops"
    )
    settings = bpy.context.scene.rigo_brace
    try:
        # ---------------- PART 1 ----------------
        _mark("PART 1 - shading through the remesh path")
        obj, centre = _fresh(settings)
        _mark("  " + _shading(obj.data, "after import + Apply Units"))
        settings.remesh_voxel = 3.0
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.view_layer.objects.active = obj
        bpy.ops.rigo.remesh()
        _mark("  " + _shading(obj.data, "after Auto-Remesh (3 mm voxels)"))
        bpy.data.objects.remove(obj, do_unlink=True)
        # CONTROL: what a raw REMESH modifier hands back with no shading
        # restoration — i.e. what the orthotist was actually looking at.
        obj, centre = _fresh(settings)
        mod = obj.modifiers.new(name="raw", type="REMESH")
        mod.mode = "VOXEL"
        mod.voxel_size = 0.003
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=mod.name)
        _mark("  " + _shading(obj.data, "CONTROL raw REMESH, no restoration"))
        bpy.data.objects.remove(obj, do_unlink=True)

        # ---------------- PART 2 ----------------
        _mark("")
        _mark("PART 2 - Smooth Area on a committed 20 mm correction")
        obj, centre = _fresh(settings)
        _paint(obj, centre, 59.0)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 20.0
        settings.region_feather = 15.0
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add()
        region = obj.rigo_regions[obj.rigo_region_index]
        group = obj.vertex_groups.get(region.surface_mask)
        bpy.ops.object.mode_set(mode="OBJECT")
        base = [v.co.copy() for v in obj.data.vertices]
        base_bvh = BVHTree.FromPolygons(
            base, [tuple(p.vertices) for p in obj.data.polygons],
            all_triangles=True,
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
        _mark(f"  committed: {_wall(me, weights)}")

        committed = [v.co.copy() for v in me.vertices]
        settings.select_smooth_factor = 0.5
        settings.select_smooth_iters = 5
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(me)
        painted = 0
        for f in bm.faces:
            if all(v.index in member for v in f.verts):
                f.select = True
                painted += 1
        bmesh.update_edit_mesh(me)
        st = bpy.ops.rigo.smooth_selection()
        bpy.ops.object.mode_set(mode="OBJECT")
        me = obj.data

        shifted = {
            i for i in range(len(committed))
            if (me.vertices[i].co - committed[i]).length > 1e-9
        }
        beyond = shifted - member
        step = 0.0
        for e in me.edges:
            a, b = e.vertices
            if (a in shifted) == (b in shifted):
                continue
            inner = a if a in shifted else b
            step = max(step, (me.vertices[inner].co - committed[inner]).length)
        core = []
        for i, w in weights.items():
            if w < 0.95:
                continue
            loc, _n, _idx, _d = base_bvh.find_nearest(me.vertices[i].co)
            if loc is not None:
                core.append((me.vertices[i].co - loc).length * 1000.0)
        core.sort()
        _mark(
            f"  Smooth Area {st}: painted {painted} faces, region has "
            f"{len(member)} verts; moved {len(shifted)} verts, of which "
            f"{len(beyond)} lie BEYOND the paint (the blend into the body)"
        )
        _mark(
            f"  cliff at the edge of the influence = {step*1000.0:.4f}mm "
            f"| depth med={core[len(core)//2]:.2f} min={core[0]:.2f}mm "
            f"of 20 authored"
        )
        _mark(f"  after: {_wall(me, weights)}")
        bpy.data.objects.remove(obj, do_unlink=True)
        _mark("")
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
